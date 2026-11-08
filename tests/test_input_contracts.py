"""Shared metadata/input contracts and rollback boundaries."""
import json
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from test_regressions import record, common, convert, zotero as z, w


class InputContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task = self.root / 'task.sqlite'
        w.init(self.task, dict(topic='test', query='test', criteria='test'))
        self.db = w.connect(self.task)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_credentials_rejected_and_entire_import_batch_rolled_back(self):
        for fields in ({'cookie': 'synthetic'}, {'Authorization': 'synthetic'},
                       {'password': 'synthetic'}, {'extra': {'access_token': 'synthetic'}},
                       {'extra': [{'refresh-token': 'synthetic'}]}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError), self.db:
                    w.import_records(self.db, [record(), record(2, **fields)])
                self.assertEqual(w.status(self.db)['papers'], 0)
                self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
                with self.assertRaises(ValueError):
                    z.prepare(record(**fields))

    def test_nullable_ledger_metadata_can_be_converted_and_prepared(self):
        value = record(year=None, volume=None, issue=None, pages=None, doi=None,
                       cnki_id=None, abstract=None)
        with self.db:
            pid = w.import_records(self.db, [value])[0]['id']
        metadata = json.loads(w.paper(self.db, pid)['metadata'])
        output, count, _ = convert.render([metadata])
        self.assertEqual(count, 1)
        self.assertNotIn('year =', output)
        self.assertNotIn('None', output)
        prepared = z.prepare(metadata)
        self.assertNotIn('date', prepared['item'])
        self.assertNotIn('DOI', prepared['item'])

    def test_invalid_ports_rejected_at_all_entry_points(self):
        for url in ('https://example.org:invalid/paper', 'https://example.org:70000/paper',
                    'https://example.org:-1/paper'):
            for check in (common.source_url, lambda u: convert.normalize(record(url=u)),
                          lambda u: z.prepare(record(url=u))):
                with self.subTest(url=url, check=check), self.assertRaises(ValueError):
                    check(url)

    def test_path_session_identifiers_not_persisted(self):
        for path in ('/paper;jsessionid=synthetic', '/paper;session_id=synthetic',
                     '/paper%3Bjsessionid%3Dsynthetic', '/sessionid/synthetic/paper'):
            url = 'https://example.org' + path
            with self.subTest(path=path), self.assertRaises(ValueError), self.db:
                w.import_records(self.db, [record(url=url)])
        self.assertEqual(w.status(self.db)['papers'], 0)

    def test_valid_ports_and_ordinary_paths_are_preserved(self):
        for url in ('https://example.org:443/paper', 'http://[::1]:8118/paper',
                    'https://example.org/session-studies/2025?author=A'):
            self.assertEqual(common.source_url(url), url)

    def test_evidence_url_scheme_is_case_insensitive(self):
        with self.db:
            pid = w.import_records(self.db, [record()])[0]['id']
            w.screen(self.db, pid, dict(decision='include', reason='synthetic', evidence='synthetic',
                                       basis='abstract', access_level='abstract_only'))
            w.extract(self.db, pid, dict(access_level='abstract_only', fields={'question': dict(
                value='synthetic', quote='synthetic', locator='摘要', source='HTTPS://example.org/1')}))
        self.assertEqual(w.stage(self.db, pid, 'extraction')['status'], 'done')
        for url in ('HTTP://example.org/paper', 'HTTPS://example.org/paper'):
            self.assertEqual(common.evidence_source(url), url)
        with self.assertRaises(ValueError):
            common.evidence_source('HTTPS://example.org/paper?token=synthetic')

    def test_config_credentials_rejected_before_task_creation(self):
        task = self.root / 'private-config.sqlite'
        with self.assertRaises(ValueError):
            w.init(task, dict(topic='test', query='test', criteria='test',
                              extra={'cookie': 'synthetic'}))
        self.assertFalse(task.exists())

    def test_screen_and_extraction_extra_credentials_do_not_change_evidence(self):
        with self.db:
            pid = w.import_records(self.db, [record()])[0]['id']
        screening = dict(decision='include', reason='synthetic', evidence='synthetic',
                         basis='abstract', access_level='abstract_only')
        with self.assertRaises(ValueError), self.db:
            w.screen(self.db, pid, dict(screening, extra={'cookie': 'synthetic'}))
        self.assertIsNone(w.paper(self.db, pid)['screening'])
        with self.db:
            w.screen(self.db, pid, screening)
        extraction = dict(access_level='abstract_only', fields={'question': dict(
            value='synthetic', quote='synthetic', locator='摘要', source=record()['url'],
            extra={'password': 'synthetic'})})
        with self.assertRaises(ValueError), self.db:
            w.extract(self.db, pid, extraction)
        self.assertIsNone(w.paper(self.db, pid)['extraction'])

    def test_legacy_credentials_are_not_exported_or_silently_removed(self):
        with self.db:
            pid = w.import_records(self.db, [record()])[0]['id']
        original = json.loads(w.paper(self.db, pid)['metadata'])
        for table in ('paper', 'history'):
            with self.subTest(table=table):
                with self.db:
                    if table == 'paper':
                        self.db.execute('UPDATE papers SET metadata=? WHERE id=?',
                                        (json.dumps(dict(original, cookie='synthetic')), pid))
                    else:
                        self.db.execute('UPDATE papers SET metadata=? WHERE id=?', (json.dumps(original), pid))
                        self.db.execute("INSERT INTO events(action,detail) VALUES ('legacy',?)",
                                        (json.dumps({'before': {'cookie': 'synthetic'}}),))
                before = self.db.total_changes
                dest = self.root / (table + '-report')
                with self.assertRaises(ValueError):
                    w.export(self.db, dest)
                self.assertFalse(dest.exists())
                self.assertEqual(self.db.total_changes, before)

    def test_legacy_session_urls_are_rejected_before_export(self):
        with self.db:
            pid = w.import_records(self.db, [record()])[0]['id']
            self.db.execute('UPDATE papers SET metadata=? WHERE id=?', (
                json.dumps(record(url='https://example.org/paper;jsessionid=synthetic')), pid))
        with self.assertRaises(ValueError):
            w.export(self.db, self.root / 'session-report')
        self.assertFalse((self.root / 'session-report').exists())

    def test_failed_connect_closes_the_opened_sqlite_connection(self):
        original_connect = sqlite3.connect
        opened = []
        class TrackedConnection(sqlite3.Connection):
            was_closed = False
            def close(self):
                self.was_closed = True
                return super().close()
        def connect(*args, **kwargs):
            result = original_connect(*args, factory=TrackedConnection, **kwargs)
            opened.append(result)
            return result
        for invalid_json in (False, True):
            bad = self.root / ('invalid-' + str(invalid_json) + '.sqlite')
            db = original_connect(str(bad))
            try:
                if invalid_json:
                    with db:
                        db.execute('CREATE TABLE meta(key TEXT, value TEXT)')
                        db.execute("INSERT INTO meta VALUES ('schema_version', 'not-json')")
            finally:
                db.close()
            with self.subTest(invalid_json=invalid_json):
                try:
                    with patch.object(w.sqlite3, 'connect', side_effect=connect):
                        with self.assertRaises((ValueError, sqlite3.Error)):
                            w.connect(bad)
                    self.assertTrue(opened[-1].was_closed)
                finally:
                    if opened and not opened[-1].was_closed:
                        opened[-1].close()

    def test_deeply_nested_json_is_reported_as_plain_cli_error(self):
        path = self.root / 'deep.json'
        path.write_text('[' * 2000 + '0' + ']' * 2000, encoding='utf-8')
        repo = Path(__file__).resolve().parents[1]
        commands = [
            ['scripts/workflow.py', '--task', str(self.root / 'deep.sqlite'), 'init', '--config', str(path)],
            ['scripts/convert.py', str(path), '--format', 'json', '--output', str(self.root / 'deep.bib')],
            ['scripts/push_to_zotero.py', str(path), '--dry-run'],
        ]
        for args in commands:
            result = subprocess.run([sys.executable, '-B'] + args, cwd=repo,
                                    capture_output=True, encoding='utf-8')
            with self.subTest(command=args[0]):
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.strip())
                self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((self.root / 'deep.sqlite').exists())
        self.assertFalse((self.root / 'deep.bib').exists())

    def test_decoder_recursion_failure_is_handled_across_python_versions(self):
        path = self.root / 'decoder.json'
        path.write_text('{}', encoding='utf-8')
        stderr = io.StringIO()
        with patch.object(json, 'loads', side_effect=RecursionError('synthetic decoder limit')), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_info:
                w.main(['--task', str(self.root / 'decoder.sqlite'), 'init', '--config', str(path)])
            self.assertEqual(exit_info.exception.code, 1)
            with patch.object(sys, 'argv', ['convert.py', str(path), '--format', 'json',
                                           '--output', str(self.root / 'decoder.bib')]):
                self.assertEqual(convert.main(), 1)
        self.assertIn('synthetic decoder limit', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
