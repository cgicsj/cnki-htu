"""Offline behavioral tests; never contact CNKI or a real Zotero library."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common
import convert
import push_to_zotero as zotero
import workflow as w


def record(i=1, **kw):
    value = dict(title='Synthetic ' + str(i), url='https://example.org/' + str(i),
                 retrieved_at='2026-10-30T10:00:00+08:00', authors=['A'],
                 authors_complete=True, year='2026', journal='Synthetic Journal',
                 database='TEST', record_id=str(i))
    value.update(kw)
    return value


class FakeClient:
    def __init__(self, code=201):
        self.code, self.writes = code, []

    def request(self, endpoint, data=None, **kw):
        if endpoint == 'getSelectedCollection':
            return 200, dict(libraryID=1, libraryEditable=True, filesEditable=True)
        self.writes.append((endpoint, data))
        return self.code, {}


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task = self.root / 'task.sqlite'
        w.init(self.task, dict(topic='synthetic', query='synthetic', criteria='synthetic',
                               stages=['screening', 'extraction', 'download']))
        self.db = w.connect(self.task)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, rec=None):
        with self.db:
            return w.import_records(self.db, [rec or record()])[0]['id']

    def test_authors_upgrade_and_history(self):
        pid = self.add(record(authors_complete=False))
        self.add(record(authors=['A', 'B']))
        actual = json.loads(w.paper(self.db, pid)['metadata'])
        self.assertEqual(actual['authors'], ['A', 'B'])
        self.assertTrue(actual['authors_complete'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE action='metadata-enriched'").fetchone()[0], 1)
        self.add(record(authors_complete=False))
        self.assertEqual(json.loads(w.paper(self.db, pid)['metadata'])['authors'], ['A', 'B'])

    def test_conflicting_complete_authors_rejected(self):
        self.add()
        with self.assertRaises(ValueError), self.db:
            w.import_records(self.db, [record(authors=['B'])])

    def test_stable_id_after_doi_upgrade_and_reopen(self):
        pid = self.add()
        self.assertEqual(self.add(record(doi='HTTPS://DOI.ORG/10.1234/ONE')), pid)
        self.db.close()
        self.db = w.connect(self.task)
        self.assertEqual(self.add(record(doi='10.1234/one')), pid)
        self.assertEqual(w.status(self.db)['papers'], 1)

    def test_url_alias_survives_reopen(self):
        pid = self.add()
        self.add(record(url='https://example.org/new'))
        self.db.close()
        self.db = w.connect(self.task)
        value = record(url='https://example.org/new')
        value.pop('database'); value.pop('record_id')
        self.assertEqual(self.add(value), pid)

    def test_same_locator_conflicting_doi_rejected(self):
        value = record(); value.pop('database'); value.pop('record_id')
        self.add(value)
        self.add(dict(value, doi='10.1234/one'))
        with self.assertRaises(ValueError), self.db:
            w.import_records(self.db, [dict(value, doi='10.1234/two')])
        self.assertEqual(w.status(self.db)['papers'], 1)

    def test_batch_conflict_rolls_back(self):
        with self.assertRaises(ValueError), self.db:
            w.import_records(self.db, [record(), record(title='Conflicting')])
        self.assertEqual(w.status(self.db)['papers'], 0)

    def test_legacy_ledger_without_alias_table(self):
        pid = self.add()
        with self.db:
            self.db.execute('DROP TABLE paper_aliases')
        self.assertEqual(self.add(record(doi='10.1234/one')), pid)

    def test_session_urls_rejected_in_all_entry_points(self):
        for query in ('token=x', '%74oken=x', '%2574oken=x', 'session_id=x', 'AUTH=x', 'cookie=', 'x=1%26token%3Dx'):
            url = 'https://example.org/paper?' + query
            for validator in (common.source_url, zotero.public_url,
                              lambda value: convert.normalize(record(url=value))):
                with self.subTest(query=query, validator=validator), self.assertRaises(ValueError):
                    validator(url)

    def test_ordinary_query_and_proxy_scope(self):
        url = 'https://example.org/paper?filename=TEST&dbcode=CJFD&author=A'
        self.assertEqual(common.source_url(url), url)
        proxy = 'http://www-cnki-net-s.vpn.htu.edu.cn:8118/paper'
        self.assertEqual(common.source_url(proxy), proxy)
        with self.assertRaises(ValueError):
            zotero.public_url(proxy)

    def test_bibtex_alias_upgrade_merges(self):
        base = record(cnki_id='TEST:1')
        output, count, warnings = convert.render([base, dict(base, doi='10.1234/one')])
        self.assertEqual(count, 1)
        self.assertIn('10.1234/one', output)
        self.assertTrue(warnings)

    def test_bibtex_database_record_id_matches_changed_url(self):
        self.assertEqual(convert.render([record(), record(url='https://example.org/new', doi='10.1234/one')])[1], 1)

    def test_distinct_strong_ids_preserved(self):
        self.assertEqual(convert.render([record(1), record(2)])[1], 2)

    def test_bibtex_conflicting_doi_rejected(self):
        with self.assertRaises(ValueError):
            convert.render([record(doi='10.1234/one'), record(doi='10.1234/two')])

    def test_legacy_zotero_receipt_upgrade_does_not_resend(self):
        client = FakeClient()
        state = self.root / 'receipt.json'
        zotero.push([record()], state, 'L1', client)
        data = json.loads(state.read_text(encoding='utf-8'))
        for row in data['records'].values():
            row.pop('aliases')  # Simulate existing v1 receipts.
        state.write_text(json.dumps(data), encoding='utf-8')
        result = zotero.push([record(doi='10.1234/one')], state, 'L1', client)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(result['results'][0]['status'], 'blocked')
        self.assertFalse(result['complete'])

    def test_zotero_batch_doi_upgrade_saves_once(self):
        client = FakeClient()
        result = zotero.push([record(), record(doi='10.1234/one')], self.root / 'receipt.json', 'L1', client)
        self.assertTrue(result['complete'])
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.writes[0][1]['items'][0]['DOI'], '10.1234/one')

    def test_zotero_conflict_validated_before_write(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            zotero.push([record(doi='10.1234/one'), record(doi='10.1234/two')], self.root / 'receipt.json', 'L1', client)
        self.assertEqual(client.writes, [])

    def test_zotero_uncertain_write_not_retried(self):
        client = FakeClient(0)
        state = self.root / 'receipt.json'
        zotero.push([record()], state, 'L1', client)
        result = zotero.push([record()], state, 'L1', client)
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(result['results'][0]['status'], 'uncertain')

    def test_zotero_same_url_conflicting_cnki_id_blocked(self):
        client = FakeClient()
        state = self.root / 'receipt.json'
        zotero.push([record()], state, 'L1', client)
        result = zotero.push([record(record_id='other')], state, 'L1', client)
        self.assertFalse(result['complete'])
        self.assertEqual(len(client.writes), 1)

    def test_ris_chinese_and_special_characters(self):
        records = convert.parse_tagged('TY  - JOUR\nTI  - 中文 & 研究\nAU  - 张三\nJO  - 示例期刊\nPY  - 2026\nER  -\n', 'ris')
        output, count, _ = convert.render(records)
        self.assertEqual(count, 1)
        self.assertIn('中文 \\& 研究', output)
        self.assertIn('{张三}', output)

    def test_command_line_examples(self):
        repo = Path(__file__).resolve().parents[1]
        task = str(self.root / 'cli.sqlite')
        commands = [
            ['scripts/workflow.py', '--task', task, 'init', '--config', 'examples/config.json'],
            ['scripts/workflow.py', '--task', task, 'import', '--input', 'examples/records.json'],
            ['scripts/workflow.py', '--task', task, 'export', '--output', str(self.root / 'cli-report')],
            ['scripts/convert.py', 'examples/records.json', '--format', 'json', '--output', str(self.root / 'citations.bib')],
            ['scripts/push_to_zotero.py', 'examples/records.json', '--dry-run'],
        ]
        for args in commands:
            result = subprocess.run([sys.executable, '-B'] + args, cwd=repo, capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)

    def test_screen_replay_preserves_extraction(self):
        pid = self.add()
        screen = dict(decision='include', reason='synthetic', evidence='synthetic',
                      basis='abstract', access_level='abstract_only')
        extract = dict(access_level='abstract_only', fields={'question': dict(
            value='synthetic', quote='synthetic', locator='摘要', source=record()['url'])})
        with self.db:
            w.screen(self.db, pid, screen)
            w.extract(self.db, pid, extract)
            w.screen(self.db, pid, screen)
        self.assertEqual(w.stage(self.db, pid, 'extraction')['status'], 'done')
        with self.db:
            w.screen(self.db, pid, dict(screen, decision='exclude'))
        self.assertIsNone(w.paper(self.db, pid)['extraction'])
        self.assertEqual(w.stage(self.db, pid, 'extraction')['status'], 'skipped')

    def test_evidence_source_validated(self):
        pid = self.add()
        with self.db:
            w.screen(self.db, pid, dict(decision='include', reason='test', evidence='test', basis='abstract', access_level='abstract_only'))
        with self.assertRaises(ValueError):
            w.extract(self.db, pid, dict(access_level='abstract_only', fields={'question': dict(
                value='test', quote='test', locator='摘要', source='https://example.org/?%74oken=x')}))

    def test_artifact_revalidation_and_claim(self):
        pid = self.add()
        path = self.root / 'synthetic.pdf'
        path.write_bytes(b'%PDF-1.7\nsynthetic\n%%EOF')
        with self.db:
            w.mark(self.db, pid, 'download', 'running')
            with self.assertRaises(ValueError):
                w.mark(self.db, pid, 'download', 'running')
            w.mark(self.db, pid, 'download', 'done', path=path, identity_verified=True)
        path.write_bytes(b'%PDF-1.7\nchanged\n%%EOF')
        checked = w.inspect_artifacts(self.db)
        with self.db:
            w.queue(self.db, checked)
        self.assertEqual(w.stage(self.db, pid, 'download')['status'], 'pending')

    def test_stale_file_check_cannot_reset_new_receipt(self):
        pid = self.add()
        path = self.root / 'synthetic.pdf'
        path.write_bytes(b'%PDF-1.7 old')
        with self.db:
            w.mark(self.db, pid, 'download', 'done', path=path, identity_verified=True)
        path.write_bytes(b'%PDF-1.7 new')
        checked = w.inspect_artifacts(self.db)
        with self.db:
            w.mark(self.db, pid, 'download', 'done', path=path, identity_verified=True)
            w.queue(self.db, checked)
        self.assertEqual(w.stage(self.db, pid, 'download')['status'], 'done')

    def test_export_xml_and_no_overwrite(self):
        self.add(record(title='=Synthetic <&>'))
        dest = self.root / 'report'
        with self.db:
            result = w.export(self.db, dest)
        with zipfile.ZipFile(result['workbook']) as archive:
            for member in archive.namelist():
                if member.endswith(('.xml', '.rels')):
                    ET.fromstring(archive.read(member))
            self.assertNotIn('<f>', archive.read('xl/worksheets/sheet1.xml').decode())
        self.assertIn("'=Synthetic", (dest / '文献筛选表.csv').read_text(encoding='utf-8-sig'))
        with self.assertRaises(FileExistsError):
            w.export(self.db, dest)

    def test_export_failure_publishes_no_partial_directory(self):
        self.add()
        dest = self.root / 'report'
        with patch.object(w, 'write_xlsx', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                w.export(self.db, dest)
        self.assertFalse(dest.exists())
        with self.db:
            w.export(self.db, dest)
        self.assertTrue((dest / 'task-snapshot.json').is_file())

    def test_publish_failure_releases_lock_for_retry(self):
        self.add()
        dest = self.root / 'report'
        with patch.object(Path, 'rename', side_effect=OSError('synthetic publication failure')):
            with self.assertRaises(OSError):
                w.export(self.db, dest)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_name(dest.name + '.publish.lock').exists())
        w.export(self.db, dest)


if __name__ == '__main__':
    unittest.main()
