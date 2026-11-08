"""Exercise real HTTP/JSON-RPC parsing against a disposable localhost server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

from test_regressions import record, synthetic_pdf, zotero as z


@contextmanager
def mcp_server(sse=False, session=False, fault=None, hold_open=False, chunked=False):
    seen = []
    release = threading.Event()
    tools = ['get_libraries', 'get_collections', 'write_item', 'add_items_to_collection']

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
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
                if method == 'tools/call' and payload['params']['name'] == 'write_item' and fault == 'no-result':
                    body = ': keep-alive\n\n'
            body = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8' if sse else 'application/json')
            if chunked:
                self.send_header('Transfer-Encoding', 'chunked')
            elif not (sse and hold_open):
                self.send_header('Content-Length', str(len(body)))
            if session and method == 'initialize':
                self.send_header('Mcp-Session-Id', 'synthetic-session')
            self.end_headers()
            if chunked:
                for offset in range(0, len(body), 7):
                    piece = body[offset:offset + 7]
                    self.wfile.write(('%x\r\n' % len(piece)).encode() + piece + b'\r\n')
            else:
                self.wfile.write(body)
            self.wfile.flush()
            if sse and hold_open:
                release.wait(5)
                self.close_connection = True
            elif chunked:
                self.wfile.write(b'0\r\n\r\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port) + '/mcp', seen
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class HTTPTransportTests(unittest.TestCase):
    def test_sse_push_finishes_before_stream_eof_including_chunked_body(self):
        # A short socket timeout makes waiting for EOF fail deterministically;
        # the server holds each stream until the test leaves its context.
        for chunked in (False, True):
            with self.subTest(chunked=chunked), tempfile.TemporaryDirectory() as td, mcp_server(sse=True, hold_open=True, chunked=chunked) as (endpoint, seen):
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                class ShortTimeout:
                    def open(self, request, timeout):
                        return opener.open(request, timeout=1)
                with patch.object(z.urllib.request, 'build_opener', return_value=ShortTimeout()):
                    mcp = z.ZoteroMCP(endpoint)
                    try:
                        root = Path(td)
                        path = root / 'paper.pdf'
                        path.write_bytes(synthetic_pdf())
                        paper = record(pdf_path=str(path), pdf_identity_verified=True)
                        state = root / 'receipt.json'
                        adapter = z.MCPAdapter(mcp, 'M1:ABCD1234')
                        self.assertTrue(z.push([paper], state, 'M1:ABCD1234', adapter)['complete'])
                        self.assertTrue(z.push([paper], state, 'M1:ABCD1234', adapter)['complete'])
                        row = next(iter(json.loads(state.read_text(encoding='utf-8'))['records'].values()))
                        self.assertEqual(row['mcp_item_key'], 'ITEM1234')
                        self.assertEqual(row['mcp_attachment_key'], 'ATTACH12')
                        writes = [p['params']['arguments']['action'] for p, _ in seen
                                  if p.get('params', {}).get('name') == 'write_item']
                        self.assertEqual(writes, ['create', 'import'])
                    finally:
                        mcp.close()

    def test_sse_without_result_times_out_and_does_not_retry_write(self):
        with tempfile.TemporaryDirectory() as td, mcp_server(sse=True, hold_open=True, fault='no-result') as (endpoint, seen):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            class ShortTimeout:
                def open(self, request, timeout):
                    return opener.open(request, timeout=1)
            with patch.object(z.urllib.request, 'build_opener', return_value=ShortTimeout()):
                mcp = z.ZoteroMCP(endpoint)
                try:
                    state = Path(td) / 'receipt.json'
                    adapter = z.MCPAdapter(mcp, 'M1:ABCD1234')
                    for _ in range(2):
                        result = z.push([record()], state, 'M1:ABCD1234', adapter)
                        self.assertFalse(result['complete'])
                        self.assertEqual(result['results'][0]['status'], 'uncertain')
                    self.assertEqual(len([p for p, _ in seen if p.get('params', {}).get('name') == 'write_item']), 1)
                finally:
                    mcp.close()

    def test_sse_multiline_unicode_ignores_comments_notifications_and_wrong_ids(self):
        frames = (': heartbeat\r\n\r\n'
                  'data: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n'
                  'data: {"jsonrpc":"2.0","id":99,"result":{}}\r\n\r\n'
                  'data: not-json\r\n\r\n'
                  'event: message\r\ndata: {"jsonrpc":"2.0","id":3,\r\n'
                  'data: "result":{"title":"中文研究"}}\r\n\r\n')
        result = z._read_sse_response(io.BytesIO(frames.encode('utf-8')), 3)
        self.assertEqual(result['result']['title'], '中文研究')

    def test_sse_missing_incomplete_and_invalid_matching_responses_are_rejected(self):
        frames = [b'', b': heartbeat\n\n',
                  b'data: {"jsonrpc":"2.0","id":99,"result":{}}\n\n',
                  b'data: {"jsonrpc":"2.0","id":3,"result":{}}\n',
                  b'data: {"jsonrpc":"2.0","id":3}\n\n',
                  b'data: {"jsonrpc":"2.0","id":3,"result":{},"error":{}}\n\n']
        for frame in frames:
            with self.subTest(frame=frame), self.assertRaises(z.MCPError):
                z._read_sse_response(io.BytesIO(frame), 3)

    def test_sse_rpc_error_is_returned_for_existing_error_handling(self):
        frame = b'data: {"jsonrpc":"2.0","id":3,"error":{"code":-32000}}\n\n'
        self.assertEqual(z._read_sse_response(io.BytesIO(frame), 3)['error']['code'], -32000)

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
