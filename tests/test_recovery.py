"""Cross-transport and manually reconciled recovery invariants (offline)."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_regressions import (
    record, synthetic_pdf, FakeClient, FakeConnector, FakeMCP,
    convert, zotero as z, w,
)


class CollectionWriter(FakeClient):
    transport = 'connector'

    def request(self, endpoint, data=None, **kwargs):
        if endpoint == 'getSelectedCollection':
            return FakeConnector().request(endpoint)
        return super().request(endpoint, data, **kwargs)


class RecordingMCP(FakeMCP):
    def __init__(self, fail=None):
        super().__init__()
        self.calls = []
        self.fail = fail

    def call(self, name, arguments=None):
        self.calls.append((name, arguments))
        if self.fail == 'collection' and name == 'add_items_to_collection':
            raise RuntimeError('Synthetic collection failure after create')
        if self.fail == 'create-key' and name == 'write_item' and arguments['action'] == 'create':
            return {'success': True}
        if self.fail == 'attachment' and name == 'write_item' and arguments['action'] == 'import':
            raise RuntimeError('Synthetic attachment timeout')
        return super().call(name, arguments)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / 'receipts.json'
        self.path = self.root / 'paper.pdf'
        self.path.write_bytes(synthetic_pdf(b'old'))

    def tearDown(self):
        self.tmp.cleanup()

    def records(self):
        return json.loads(self.state.read_text(encoding='utf-8'))['records']

    def pdf_record(self):
        return record(pdf_path=str(self.path), pdf_identity_verified=True)

    def mcp_push(self, papers, target='C1', mcp=None):
        with patch.object(z, 'Client', FakeConnector):
            return z.push(papers, self.state, target,
                          z.MCPAdapter(mcp or RecordingMCP(), target))

    def test_mcp_to_connector_saved_and_uncertain_do_not_resend(self):
        for fail in (None, 'collection', 'create-key'):
            with self.subTest(fail=fail):
                self.state = self.root / ('transport-' + str(fail) + '.json')
                self.mcp_push([record()], mcp=RecordingMCP(fail))
                connector = CollectionWriter()
                result = z.push([record()], self.state, 'C1', connector)
                self.assertEqual(connector.writes, [])
                self.assertEqual(len(self.records()), 1)
                self.assertEqual(result['complete'], fail is None)

    def test_legacy_unmapped_canonical_receipt_blocks_connector(self):
        self.mcp_push([record()])
        data = json.loads(self.state.read_text(encoding='utf-8'))
        for row in data['records'].values():
            row.pop('target_aliases')
        self.state.write_text(json.dumps(data), encoding='utf-8')
        connector = CollectionWriter()
        result = z.push([record()], self.state, 'C1', connector)
        self.assertFalse(result['complete'])
        self.assertEqual(result['results'][0]['status'], 'blocked')
        self.assertEqual(connector.writes, [])
        self.assertEqual(len(self.records()), 1)
        # An MCP run observes the mapping; subsequent Connector runs can reuse it.
        self.mcp_push([record()])
        self.assertTrue(z.push([record()], self.state, 'C1', connector)['complete'])
        self.assertEqual(connector.writes, [])

    def test_distinct_verified_collection_still_creates_its_own_item(self):
        self.mcp_push([record()])
        class OtherCollection(CollectionWriter):
            def request(self, endpoint, data=None, **kwargs):
                if endpoint == 'getSelectedCollection':
                    return 200, dict(id=2, libraryID=1, name='Other',
                                     libraryEditable=True, filesEditable=True)
                return super().request(endpoint, data, **kwargs)
        connector = OtherCollection()
        self.assertTrue(z.push([record()], self.state, 'C2', connector)['complete'])
        self.assertEqual(len(connector.writes), 1)
        self.assertEqual(len(self.records()), 2)

    def test_connector_cannot_upload_against_mcp_parent_session(self):
        self.mcp_push([record()])
        connector = CollectionWriter()
        result = z.push([self.pdf_record()], self.state, 'C1', connector)
        self.assertEqual(result['results'][0]['metadata'], 'saved')
        self.assertFalse(result['complete'])
        self.assertEqual(connector.writes, [])
        mcp = RecordingMCP()
        self.assertTrue(self.mcp_push([self.pdf_record()], mcp=mcp)['complete'])
        self.assertEqual([args['action'] for name, args in mcp.calls], ['import'])

    def test_legacy_connector_session_survives_mcp_target_migration(self):
        connector = CollectionWriter()
        z.push([record()], self.state, 'C1', connector)
        # Emulate a pre-transport-field Connector receipt.
        data = json.loads(self.state.read_text(encoding='utf-8'))
        for row in data['records'].values():
            row.pop('metadata_transport')
        self.state.write_text(json.dumps(data), encoding='utf-8')
        self.mcp_push([record()])
        result = z.push([self.pdf_record()], self.state, 'C1', connector)
        self.assertTrue(result['complete'])
        self.assertEqual([name.split('?')[0] for name, _ in connector.writes],
                         ['saveItems', 'saveAttachment'])

    def test_completed_pdf_receipt_survives_transport_change(self):
        connector = CollectionWriter()
        z.push([self.pdf_record()], self.state, 'C1', connector)
        mcp = RecordingMCP()
        self.assertTrue(self.mcp_push([self.pdf_record()], mcp=mcp)['complete'])
        self.assertEqual(mcp.calls, [])
        connector.writes.clear()
        self.assertTrue(z.push([self.pdf_record()], self.state, 'C1', connector)['complete'])
        self.assertEqual(connector.writes, [])

    def test_metadata_not_saved_archives_and_releases_old_item_key(self):
        self.mcp_push([record()], mcp=RecordingMCP('collection'))
        key, before = next(iter(self.records().items()))
        self.assertEqual(before['metadata'], 'uncertain')
        self.assertEqual(before['mcp_item_key'], 'ITEM1234')
        z.resolve(self.state, key, 'metadata', 'not-saved', 'Verified original item removed')
        after = self.records()[key]
        self.assertIsNone(after['mcp_item_key'])
        self.assertIsNone(after['mcp_attachment_key'])
        self.assertNotEqual(before['session'], after['session'])
        self.assertEqual(after['reconciliation'][-1]['previous']['mcp_item_key'], 'ITEM1234')
        self.mcp_push([record()], mcp=RecordingMCP('create-key'))
        z.resolve(self.state, key, 'metadata', 'saved', 'Verified new item', 'NEWI1234')
        self.assertEqual(self.records()[key]['mcp_item_key'], 'NEWI1234')

    def test_pdf_not_saved_allows_replacement_without_new_parent(self):
        self.mcp_push([self.pdf_record()], mcp=RecordingMCP('attachment'))
        key, before = next(iter(self.records().items()))
        self.assertEqual(before['pdf'], 'uncertain')
        z.resolve(self.state, key, 'pdf', 'not-saved', 'Verified no attachment exists')
        after = self.records()[key]
        self.assertIsNone(after['pdf_sha256'])
        self.assertIsNone(after['mcp_attachment_key'])
        self.assertEqual(after['mcp_item_key'], 'ITEM1234')
        self.assertEqual(after['reconciliation'][-1]['previous']['pdf_sha256'], before['pdf_sha256'])
        self.path.write_bytes(synthetic_pdf(b'new verified copy'))
        mcp = RecordingMCP()
        self.assertTrue(self.mcp_push([self.pdf_record()], mcp=mcp)['complete'])
        self.assertEqual([args['action'] for name, args in mcp.calls], ['import'])

    def test_uncertain_pdf_is_not_retried_without_reconciliation(self):
        self.mcp_push([self.pdf_record()], mcp=RecordingMCP('attachment'))
        mcp = RecordingMCP()
        result = self.mcp_push([self.pdf_record()], mcp=mcp)
        self.assertFalse(result['complete'])
        self.assertEqual(mcp.calls, [])

    def test_invalid_receipt_is_rejected_before_any_new_item_write(self):
        z.push([record()], self.state, 'L1', FakeClient())
        original = json.loads(self.state.read_text(encoding='utf-8'))
        key = next(iter(original['records']))
        cases = [('metadata', 'invalid-status'), ('pdf', None), ('aliases', 'not-a-list'),
                 ('target_aliases', ['wrong-target']), ('mcp_item_key', 'invalid'),
                 ('pdf_sha256', 'invalid'), ('reconciliation', {}), ('session', None),
                 ('fingerprint', 'invalid'), ('metadata_transport', 'unknown'),
                 ('pdf', 'saved')]
        for field, value in cases:
            with self.subTest(field=field):
                data = json.loads(json.dumps(original))
                data['records'][key][field] = value
                self.state.write_text(json.dumps(data), encoding='utf-8')
                client = FakeClient()
                with self.assertRaises(ValueError):
                    z.push([record(2), record()], self.state, 'L1', client)
                self.assertEqual(client.writes, [])
                self.assertEqual(json.loads(self.state.read_text(encoding='utf-8')), data)

    def test_legacy_null_aliases_are_enriched_without_resending(self):
        z.push([record()], self.state, 'L1', FakeClient())
        data = json.loads(self.state.read_text(encoding='utf-8'))
        next(iter(data['records'].values()))['aliases'] = None
        self.state.write_text(json.dumps(data), encoding='utf-8')
        client = FakeClient()
        self.assertTrue(z.push([record()], self.state, 'L1', client)['complete'])
        self.assertEqual(client.writes, [])

    def test_exception_after_sending_is_not_retried(self):
        class CrashClient(FakeClient):
            def request(self, endpoint, data=None, **kwargs):
                if endpoint == 'saveItems':
                    raise OSError('Synthetic process interruption during write')
                return super().request(endpoint, data, **kwargs)
        with self.assertRaises(OSError):
            z.push([record()], self.state, 'L1', CrashClient())
        self.assertEqual(next(iter(self.records().values()))['metadata'], 'sending')
        client = FakeClient()
        result = z.push([record()], self.state, 'L1', client)
        self.assertFalse(result['complete'])
        self.assertEqual(client.writes, [])

    def test_concurrent_push_rejects_second_writer(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        class PausedClient(FakeClient):
            def request(self, endpoint, data=None, **kwargs):
                if endpoint == 'saveItems':
                    entered.set()
                    if not release.wait(10):
                        raise TimeoutError('Test did not release writer')
                return super().request(endpoint, data, **kwargs)
        first, second = PausedClient(), FakeClient()
        def run_first():
            try:
                z.push([record()], self.state, 'L1', first)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run_first)
        thread.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaises(RuntimeError):
                z.push([record()], self.state, 'L1', second)
        finally:
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(first.writes), 1)
        self.assertEqual(second.writes, [])

    def test_ledger_cli_claim_is_atomic_between_processes(self):
        task = self.root / 'claim.sqlite'
        w.init(task, dict(topic='synthetic', query='synthetic', criteria='synthetic',
                          stages=['download']))
        db = w.connect(task)
        try:
            with db:
                pid = w.import_records(db, [record()])[0]['id']
        finally:
            db.close()
        repo = Path(__file__).resolve().parents[1]
        command = [sys.executable, '-B', str(repo / 'scripts' / 'workflow.py'),
                   '--task', str(task), 'mark', '--id', pid,
                   '--stage', 'download', '--status', 'running']
        processes = [subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, encoding='utf-8') for _ in range(2)]
        try:
            outputs = [process.communicate(timeout=20) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 1], outputs)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        db = w.connect(task)
        try:
            self.assertEqual(w.stage(db, pid, 'download')['status'], 'running')
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE action='download:running'").fetchone()[0], 1)
        finally:
            db.close()

    def test_blocked_metadata_never_reports_saved(self):
        z.push([record()], self.state, 'L1', FakeClient())
        data = json.loads(self.state.read_text(encoding='utf-8'))
        next(iter(data['records'].values()))['metadata'] = 'blocked'
        self.state.write_text(json.dumps(data), encoding='utf-8')
        client = FakeClient()
        result = z.push([record()], self.state, 'L1', client)
        self.assertFalse(result['complete'])
        self.assertEqual(result['results'][0]['status'], 'blocked')
        self.assertEqual(client.writes, [])

    def test_temporary_download_is_rejected_before_metadata_write(self):
        for extension in ('.crdownload', '.part', '.partial', '.tmp'):
            with self.subTest(extension=extension):
                path = self.root / ('paper' + extension)
                path.write_bytes(synthetic_pdf())
                client = FakeClient()
                with self.assertRaises(ValueError):
                    z.push([record(pdf_path=str(path), pdf_identity_verified=True)],
                           self.state, 'L1', client)
                self.assertEqual(client.writes, [])

    def test_empty_push_rejected_without_contacting_zotero(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            z.push([], self.state, 'L1', client)
        self.assertEqual(client.writes, [])
        self.assertFalse(self.state.exists())

    def test_bibtex_keys_are_unique_and_stable_for_retained_url_records(self):
        first = record()
        first.pop('database')
        first.pop('record_id')
        second = dict(first, url='https://example.org/other')
        metadata_only = dict(first)
        metadata_only.pop('url')
        def keys(records):
            output, count, _ = convert.render(records)
            actual = re.findall(r'@article\{([^,]+),', output)
            self.assertEqual(len(set(actual)), count)
            return actual
        actual = keys([first, second, metadata_only])
        self.assertEqual(len(actual), 3)
        self.assertEqual(set(actual), set(keys([metadata_only, second, first])))
        self.assertEqual(len(keys([first, dict(first)])), 1)


if __name__ == '__main__':
    unittest.main()
