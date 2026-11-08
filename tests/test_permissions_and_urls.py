"""Host-policy and cross-transport permission regressions; no external writes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_regressions import common, zotero as z, record, synthetic_pdf, FakeMCP, FakeConnector


class PermissionAndURLTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pdf = self.root / 'synthetic.pdf'
        self.pdf.write_bytes(synthetic_pdf())

    def tearDown(self):
        self.tmp.cleanup()

    def adapter(self, field, library, collection, connector):
        mcp = FakeMCP()
        mcp.libraries[0][field] = library
        mcp.targets[0][field] = collection
        class Connector(FakeConnector):
            def request(self, endpoint, data=None, **kwargs):
                code, value = super().request(endpoint, data, **kwargs)
                return code, dict(value, **{field: connector})
        adapter = z.MCPAdapter(mcp, 'C1')
        adapter.connector = Connector()
        return adapter, mcp

    def test_proxy_dns_variants_rejected_before_zotero_write(self):
        for host in ('vpn.htu.edu.cn.', 'WWW-CNKI-NET-S.VPN.HTU.EDU.CN.',
                     'www-cnki-net-s.vpn.htu.edu.cn%2e',
                     'www-cnki-net-s.vpn.htu.edu.cn。'):
            url = 'http://' + host + ':8118/paper'
            with self.subTest(host=host):
                self.assertEqual(common.source_url(url), url)  # Local access remains allowed.
                client = FakeConnector()
                with patch.object(client, 'request', wraps=client.request) as request:
                    with self.assertRaises(ValueError):
                        z.push([record(url=url)], self.root / 'receipt.json', 'C1', client)
                    request.assert_not_called()

    def test_public_hosts_not_rewritten_or_confused_with_proxy(self):
        for host in ('example.org.', 'vpn.htu.edu.cn.example.org', 'notvpn.htu.edu.cn'):
            url = 'https://' + host + '/paper'
            self.assertEqual(z.prepare(record(url=url))['item']['url'], url)

    def test_c_target_honors_readonly_from_each_scope_before_metadata_write(self):
        for index, flags in enumerate(((False, True, True), (True, False, True), (True, True, False))):
            with self.subTest(flags=flags):
                adapter, mcp = self.adapter('libraryEditable', *flags)
                state = self.root / (str(index) + '.json')
                with patch.object(mcp, 'call', wraps=mcp.call) as call:
                    with self.assertRaises(RuntimeError):
                        z.push([record()], state, 'C1', adapter)
                    call.assert_not_called()
                self.assertFalse(state.exists())

    def test_c_target_honors_file_denial_before_any_write(self):
        for index, flags in enumerate(((False, True, True), (True, False, True), (True, True, False))):
            with self.subTest(flags=flags):
                adapter, mcp = self.adapter('filesEditable', *flags)
                state = self.root / (str(index) + '.json')
                with patch.object(mcp, 'call', wraps=mcp.call) as call:
                    with self.assertRaises(RuntimeError):
                        z.push([record(pdf_path=str(self.pdf), pdf_identity_verified=True)], state, 'C1', adapter)
                    call.assert_not_called()
                self.assertFalse(state.exists())

    def test_unknown_mcp_permissions_can_use_confirmed_connector_permission(self):
        for field in ('libraryEditable', 'filesEditable'):
            with self.subTest(field=field):
                adapter, mcp = self.adapter(field, None, None, True)
                result = z.push([record(pdf_path=str(self.pdf), pdf_identity_verified=True)],
                                self.root / (field + '.json'), 'C1', adapter)
                self.assertTrue(result['complete'])

    def test_unknown_file_permission_is_not_promoted_to_true(self):
        adapter, mcp = self.adapter('filesEditable', None, None, None)
        with patch.object(mcp, 'call', wraps=mcp.call) as call:
            with self.assertRaises(RuntimeError):
                z.push([record(pdf_path=str(self.pdf), pdf_identity_verified=True)],
                       self.root / 'unknown.json', 'C1', adapter)
            call.assert_not_called()

    def test_inventory_collection_cannot_override_library_denial(self):
        mcp = object.__new__(z.ZoteroMCP)
        def call(name, arguments=None):
            if name == 'get_libraries':
                return [dict(libraryID=1, libraryType='group', libraryEditable=False,
                             editable=True, filesEditable=False)]
            if name == 'get_collections':
                return [dict(key='ABCD1234', name='Synthetic Collection',
                             libraryEditable=True, filesEditable=True)]
            raise AssertionError(name)
        mcp.call = call
        libraries, targets = mcp.inventory()
        self.assertIs(libraries[0]['libraryEditable'], False)
        self.assertTrue(all(row['libraryEditable'] is False for row in targets))
        self.assertTrue(all(row['filesEditable'] is False for row in targets))
        with self.assertRaises(RuntimeError):
            z.selected(z.MCPAdapter(mcp, 'M1:ABCD1234'))


if __name__ == '__main__':
    unittest.main()
