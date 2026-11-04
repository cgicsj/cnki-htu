"""Exercise real HTTP/JSON-RPC parsing against a disposable localhost server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from test_regressions import record, synthetic_pdf, zotero as z


@contextmanager
def mcp_server(sse=False, session=False, fault=None):
    seen = []
    tools = ['get_libraries', 'get_collections', 'write_item', 'add_items_to_collection']

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_DELETE(self):
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((payload, dict(self.headers)))
            method = payload['method']
            if method == 'notifications/initialized':
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            response_id = payload['id']
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {},
                          'serverInfo': {'name': 'synthetic', 'version': '1'}}
            elif method == 'tools/list':
                result = {'tools': [{'name': name} for name in tools]}
            else:
                params = payload['params']
                name, arguments = params['name'], params['arguments']
                if name == 'get_libraries':
                    value = [{'libraryID': 1, 'libraryType': 'user', 'name': 'Test'}]
                elif name == 'get_collections':
                    value = [{'key': 'ABCD1234', 'name': 'Synthetic Collection'}]
                elif name == 'add_items_to_collection':
                    value = {'success': True}
                elif arguments['action'] == 'create':
                    value = {'itemKey': 'ITEM1234'}
                    if fault == 'wrong-id':
                        response_id = 999
                else:
                    value = {'attachmentKey': 'ATTACH12'}
                result = {'content': [{'type': 'text', 'text': json.dumps(value)}]}
            response = {'jsonrpc': '2.0', 'id': response_id, 'result': result}
            body = json.dumps(response)
            if sse:
                noise = json.dumps({'jsonrpc': '2.0', 'id': 777, 'result': {'unrelated': True}})
                body = 'data: ' + noise + '\n\ndata: ' + body + '\n\n'
            body = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if sse else 'application/json')
            self.send_header('Content-Length', str(len(body)))
            if session and method == 'initialize':
                self.send_header('Mcp-Session-Id', 'synthetic-session')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port) + '/mcp', seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class HTTPTransportTests(unittest.TestCase):
    def test_json_and_sse_push_metadata_and_pdf_with_and_without_sessions(self):
        for sse in (False, True):
            for session in (False, True):
                with self.subTest(sse=sse, session=session), tempfile.TemporaryDirectory() as td, mcp_server(sse, session) as (endpoint, seen):
                    root = Path(td)
                    path = root / 'paper.pdf'
                    path.write_bytes(synthetic_pdf())
                    mcp = z.ZoteroMCP(endpoint)
                    try:
                        paper = record(pdf_path=str(path), pdf_identity_verified=True)
                        result = z.push([paper], root / 'receipts.json', 'M1:ABCD1234',
                                        z.MCPAdapter(mcp, 'M1:ABCD1234'))
                        self.assertTrue(result['complete'], result)
                        for payload, headers in seen:
                            if payload['method'] != 'initialize':
                                lower = {key.lower(): value for key, value in headers.items()}
                                self.assertEqual(lower.get('mcp-protocol-version'), '2024-11-05')
                                self.assertEqual(lower.get('mcp-session-id'),
                                                 'synthetic-session' if session else None)
                        writes = [p['params']['arguments'] for p, _ in seen
                                  if p.get('params', {}).get('name') == 'write_item']
                        self.assertEqual([args['action'] for args in writes], ['create', 'import'])
                    finally:
                        mcp.close()

    def test_unmatched_response_preserves_uncertain_receipt_without_retry(self):
        for sse in (False, True):
            with self.subTest(sse=sse), tempfile.TemporaryDirectory() as td, mcp_server(sse=sse, fault='wrong-id') as (endpoint, seen):
                mcp = z.ZoteroMCP(endpoint)
                try:
                    state = Path(td) / 'receipts.json'
                    adapter = z.MCPAdapter(mcp, 'M1:ABCD1234')
                    result = z.push([record()], state, 'M1:ABCD1234', adapter)
                    self.assertFalse(result['complete'])
                    self.assertEqual(result['results'][0]['status'], 'uncertain')
                    z.push([record()], state, 'M1:ABCD1234', adapter)
                    writes = [p for p, _ in seen if p.get('params', {}).get('name') == 'write_item']
                    self.assertEqual(len(writes), 1)
                finally:
                    mcp.close()

    def test_rpc_envelope_rejects_missing_or_ambiguous_results(self):
        for response in ({}, [], {'jsonrpc': '2.0', 'id': 3},
                         {'jsonrpc': '2.0', 'id': 3, 'result': {}, 'error': {}},
                         {'jsonrpc': '2.0', 'id': True, 'result': {}},
                         {'id': 3, 'result': {}},
                         {'jsonrpc': '2.0', 'id': '3', 'result': {}}):
            with self.subTest(response=response), self.assertRaises(z.MCPError):
                z.rpc_response(response, 3)


if __name__ == '__main__':
    unittest.main()
