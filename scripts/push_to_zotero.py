#!/usr/bin/env python3
"""Save verified CNKI metadata and local PDFs through Zotero MCP when available.

Independent implementation informed by cookjohn/cnki-skills. No CNKI network
requests, cookies, cloud API keys, or automatic retries after uncertain writes.
"""
import argparse
from contextlib import contextmanager
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit, parse_qsl, unquote
import uuid

from convert import normalize
from common import aliases, legacy_identities, merge_metadata, source_url, reject_credentials

API = 'http://127.0.0.1:23119/connector/'
MCP_API = os.environ.get('ZOTERO_MCP_URL', 'http://127.0.0.1:23120/mcp')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def public_url(value):
    return source_url(value, allow_proxy=False) if value else ''


def parse_elearning(text):
    text = html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', text, flags=re.I)))
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if sep:
            fields[key.strip()] = value.strip()
    mapping = {'title': 'Title-题名', 'journal': 'Source-刊名', 'year': 'Year-年',
               'volume': 'Roll-卷', 'issue': 'Period-期', 'pages': 'Page-页码',
               'abstract': 'Summary-摘要', 'url': 'Link-链接', 'doi': 'DOI'}
    result = {key: fields.get(field, '') for key, field in mapping.items()}
    result['authors'] = [s.strip() for s in re.split('[;；]', fields.get('Author-作者', '')) if s.strip()]
    result['keywords'] = [s.strip() for s in re.split('[;；]', fields.get('Keyword-关键词', '')) if s.strip()]
    return result


def prepare(raw):
    if not isinstance(raw, dict):
        raise ValueError('Each paper must be an object')
    reject_credentials(raw)
    if any(k.lower() in ('cookies', 'cookie', 'password', 'authorization', 'pdfurl', 'token') for k in raw):
        raise ValueError('Credentials and remote PDF URLs are not accepted; use a verified local pdf_path')
    rec = parse_elearning(raw['ELEARNING']) if 'ELEARNING' in raw else {}
    rec.update({k: v for k, v in raw.items() if k != 'ELEARNING'})
    if 'journal' not in rec and 'source' in rec:
        rec['journal'] = rec['source']
    if not rec.get('cnki_id') and rec.get('database') and rec.get('record_id'):
        rec['cnki_id'] = str(rec['database']) + ':' + str(rec['record_id'])
    rec['url'] = public_url(rec.get('url', ''))
    meta = normalize(rec)
    item = {
        'itemType': 'journalArticle', 'title': meta['title'],
        'creators': [{'name': a, 'creatorType': 'author'} for a in meta['authors']],
        'publicationTitle': meta['journal'], 'libraryCatalog': 'CNKI',
        'attachments': [],
    }
    for src, dest in [('year', 'date'), ('volume', 'volume'), ('issue', 'issue'),
                      ('pages', 'pages'), ('doi', 'DOI'), ('url', 'url')]:
        if meta.get(src):
            item[dest] = meta[src]
    for src, dest in [('abstract', 'abstractNote'), ('issn', 'ISSN'), ('language', 'language')]:
        if rec.get(src):
            if not isinstance(rec[src], str):
                raise ValueError(src + ' must be a string')
            item[dest] = rec[src]
    keywords = rec.get('keywords', [])
    if not isinstance(keywords, list) or any(not isinstance(k, str) for k in keywords):
        raise ValueError('keywords must be a string array')
    item['tags'] = [{'tag': k, 'type': 1} for k in keywords if k.strip()]
    identity = ('doi', meta['doi']) if meta.get('doi') else (
        ('cnki', meta['cnki_id']) if meta.get('cnki_id') else
        ('metadata', meta['title'], meta.get('year', ''), meta['journal'], meta['authors']))
    pdf = None
    if rec.get('pdf_path'):
        if rec.get('pdf_identity_verified') is not True:
            raise ValueError('Open/read the PDF, verify its paper identity, then set pdf_identity_verified=true')
        path = Path(rec['pdf_path']).expanduser()
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise ValueError('pdf_path must be an existing absolute regular file path')
        if path.suffix.lower() in ('.crdownload', '.part', '.partial', '.tmp'):
            raise ValueError('PDF still has a temporary filename; confirm download completion first')
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError('PDF exceeds the 200 MiB in-memory upload limit')
        with path.open('rb') as handle:
            header = handle.read(5)
            handle.seek(max(0, path.stat().st_size - 4096))
            trailer = handle.read()
            if header != b'%PDF-' or b'%%EOF' not in trailer:
                raise ValueError('File does not have PDF framing; HTML, CAJ and incomplete downloads are rejected')
            handle.seek(0)
            sha = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                sha.update(chunk)
        pdf = {'path': str(path), 'sha256': sha.hexdigest()}
    return {'metadata': meta, 'aliases': aliases(meta), 'legacy_keys': [digest(key) for key in legacy_identities(meta)], 'identity': digest(identity), 'fingerprint': digest(item), 'item': item, 'pdf': pdf}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    transport = 'connector'

    def __init__(self):
        # VPN/system HTTP proxy settings must not carry this localhost request elsewhere.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, endpoint, data=None, blob=None, metadata=None):
        body = blob if blob is not None else json.dumps(data or {}, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/pdf' if blob is not None else 'application/json',
                   'X-Zotero-Connector-API-Version': '3'}
        if metadata is not None:
            headers['X-Metadata'] = json.dumps(metadata, ensure_ascii=True)
        req = urllib.request.Request(API + endpoint, data=body, headers=headers)
        try:
            try:
                with self.opener.open(req, timeout=60 if blob is not None else 15) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as exc:
                with exc:
                    status, raw = exc.code, exc.read()
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            return 0, {'error': 'connection_error_or_timeout'}
        try:
            return status, json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return status, {'error': 'non_json_response'}


class MCPUnavailable(RuntimeError):
    """The MCP endpoint cannot be initialized before any write is attempted."""


class MCPError(RuntimeError):
    pass


def rpc_response(value, expected_id):
    if (not isinstance(value, dict) or value.get('jsonrpc') != '2.0'
            or type(value.get('id')) is not type(expected_id) or value.get('id') != expected_id
            or ('result' in value) == ('error' in value)):
        raise MCPError('Zotero MCP returned an invalid or unmatched JSON-RPC response')
    return value


def _permission(value):
    """Return an explicit MCP permission flag, or None when it is unknown."""
    return value if isinstance(value, bool) else None


def _combined_permission(*values):
    """An explicit denial from either transport/scope overrides permission."""
    flags = [_permission(value) for value in values]
    if False in flags:
        return False
    return True if True in flags else None


def _sse_messages(raw):
    """Collect SSE data fields per event, joining multi-line payloads."""
    messages, data = [], []
    for line in raw.splitlines():
        if line.startswith('data:'):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            messages.append('\n'.join(data))
            data = []
    if data:
        messages.append('\n'.join(data))
    return messages


def _sse_lines(response):
    """Split streaming bytes on LF, CRLF or CR without waiting after CR."""
    pending, after_cr = bytearray(), False
    while True:
        chunk = response.read1(65536)
        if not chunk:
            return  # An unterminated line is not a complete SSE event.
        for byte in chunk:
            if after_cr and byte == 10:
                after_cr = False
                continue
            after_cr = byte == 13
            if byte in (10, 13):
                yield bytes(pending)
                pending.clear()
            else:
                pending.append(byte)


def _read_sse_response(response, expected_id):
    """Return a matching, complete SSE event without waiting for stream EOF."""
    data, first_line = [], True
    for raw_line in _sse_lines(response):
        line = raw_line.decode('utf-8')
        if first_line:
            line = line.lstrip('\ufeff')
            first_line = False
        if line.startswith('data:'):
            value = line[5:]
            data.append(value[1:] if value.startswith(' ') else value)
        elif line == '' and data:
            message = '\n'.join(data)
            data = []
            try:
                item = json.loads(message)
            except ValueError:
                continue
            if (isinstance(item, dict) and type(item.get('id')) is type(expected_id)
                    and item.get('id') == expected_id):
                return rpc_response(item, expected_id)
    raise MCPError('Zotero MCP SSE stream ended without a complete matching response')


def _mcp_value(result):
    """Unwrap common MCP tool-result shapes into Python data."""
    if not isinstance(result, dict):
        return result
    if result.get('isError'):
        raise MCPError('Zotero MCP tool returned an error')
    if 'structuredContent' in result:
        return result['structuredContent']
    content = result.get('content')
    if isinstance(content, list):
        values = []
        for part in content:
            if not isinstance(part, dict) or part.get('type') != 'text':
                continue
            value = part.get('text', '')
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
            values.append(value)
        if len(values) == 1:
            return values[0]
        return values
    return result


class ZoteroMCP:
    """Small Streamable HTTP MCP client for the locally configured Zotero server."""

    def __init__(self, endpoint=None):
        from urllib.parse import urlsplit
        self.endpoint = endpoint or MCP_API
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise MCPUnavailable('Zotero MCP endpoint must be a local HTTP address')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.session_id = None
        self.protocol_version = '2024-11-05'
        self._inventory = None
        try:
            result, headers = self._post({
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': self.protocol_version, 'capabilities': {},
                           'clientInfo': {'name': 'cnki-htu', 'version': '1.0'}},
            }, initialize=True)
            self.session_id = next((v for k, v in headers.items() if k.lower() == 'mcp-session-id'), None)
            self.protocol_version = result.get('result', {}).get('protocolVersion', self.protocol_version)
            if 'error' in result:
                raise MCPUnavailable('Zotero MCP initialization failed')
            self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {}})
            self.tools = set()
            cursor, seen_cursors = None, set()
            while True:
                params = {} if cursor is None else {'cursor': cursor}
                listed = self._post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': params})[0]
                page = listed.get('result')
                if 'error' in listed or not isinstance(page, dict) or not isinstance(page.get('tools'), list):
                    raise MCPUnavailable('Zotero MCP returned an invalid tool page')
                for tool in page['tools']:
                    if not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or not tool['name']:
                        raise MCPUnavailable('Zotero MCP returned an invalid tool record')
                    self.tools.add(tool['name'])
                cursor = page.get('nextCursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or cursor in seen_cursors:
                    raise MCPUnavailable('Zotero MCP returned an invalid or repeated tool cursor')
                seen_cursors.add(cursor)
            required = {'get_libraries', 'get_collections', 'write_item', 'add_items_to_collection'}
            if not required.issubset(self.tools):
                raise MCPUnavailable('Zotero MCP lacks required library/write tools')
        except MCPUnavailable:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise MCPUnavailable('Zotero MCP is unavailable: ' + type(exc).__name__) from exc

    def _post(self, payload, initialize=False):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session_id and not initialize:
            headers['Mcp-Session-Id'] = self.session_id
        if not initialize:
            headers['MCP-Protocol-Version'] = self.protocol_version
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with self.opener.open(request, timeout=20) as response:
            response_headers = dict(response.headers.items())
            content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type == 'text/event-stream':
                if 'id' not in payload:
                    raise MCPError('Zotero MCP returned an SSE stream for a notification')
                return _read_sse_response(response, payload['id']), response_headers
            raw = response.read().decode('utf-8', 'replace')
        if not raw.strip() and payload.get('method', '').startswith('notifications/'):
            return {}, response_headers
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise MCPError('Zotero MCP returned a non-JSON response') from exc
        return rpc_response(value, payload['id']), response_headers

    def call(self, name, arguments=None):
        if name not in self.tools:
            raise MCPError('Zotero MCP tool is unavailable: ' + name)
        response, _ = self._post({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                  'params': {'name': name, 'arguments': arguments or {}}})
        if 'error' in response:
            raise MCPError('Zotero MCP call failed: ' + name)
        value = _mcp_value(response.get('result', {}))
        if isinstance(value, dict) and (value.get('success') is False or value.get('error')):
            raise MCPError('Zotero MCP tool reported failure: ' + name)
        if isinstance(value, str) and value.lstrip().lower().startswith(('error:', 'failed:')):
            raise MCPError('Zotero MCP tool reported failure: ' + name)
        return value

    def inventory(self, refresh=False):
        if not refresh and getattr(self, '_inventory', None) is not None:
            return self._inventory
        libraries = self.call('get_libraries', {'limit': 500})
        if not isinstance(libraries, list):
            raise MCPError('Zotero MCP returned an invalid library list')
        enriched, targets = [], []
        for library in libraries:
            if not isinstance(library, dict) or library.get('libraryID') is None:
                raise MCPError('Zotero MCP returned an invalid library record')
            library_id = int(library['libraryID'])
            library_type = str(library.get('libraryType', '')).lower()
            library_editable = _combined_permission(library.get('libraryEditable'), library.get('editable'))
            files_editable = _permission(library.get('filesEditable'))
            if library_type == 'feed':
                library_editable = False
                files_editable = False
            if library_editable is None and library_type == 'user':
                library_editable = True
            if files_editable is None and library_type == 'user':
                files_editable = True
            enriched.append(dict(library, libraryEditable=library_editable,
                                 filesEditable=files_editable))
            targets.append({'target': 'L' + str(library_id), 'libraryID': library_id,
                            'name': library.get('name', ''), 'type': 'library',
                            'libraryType': library_type,
                            'libraryEditable': library_editable, 'filesEditable': files_editable})
            collections = self.call('get_collections', {'libraryID': library_id, 'recursive': True})
            def flatten(rows):
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict) or not row.get('key'):
                        continue
                    collection_editable = _combined_permission(
                        row.get('libraryEditable'), row.get('editable'), library_editable)
                    collection_files = _combined_permission(row.get('filesEditable'), files_editable)
                    targets.append({'target': f'M{library_id}:{row["key"]}', 'libraryID': library_id,
                                    'collectionKey': row['key'], 'name': row.get('name', ''),
                                    'path': row.get('path', row.get('name', '')), 'type': 'collection',
                                    'libraryType': library_type, 'libraryEditable': collection_editable,
                                    'filesEditable': collection_files})
                    flatten(row.get('subcollections', []))
            flatten(collections)
        self._inventory = (enriched, targets)
        return self._inventory

    def close(self):
        if not self.session_id:
            return
        request = urllib.request.Request(self.endpoint, method='DELETE', headers={
            'Mcp-Session-Id': self.session_id, 'MCP-Protocol-Version': self.protocol_version})
        try:
            with self.opener.open(request, timeout=2):
                pass
        except Exception:
            pass


def _attachment_key(value):
    """Find only an explicit attachmentKey; parent item keys are not evidence."""
    if isinstance(value, dict):
        candidate = value.get('attachmentKey')
        if isinstance(candidate, str) and re.fullmatch(r'[A-Z0-9]{8}', candidate):
            return candidate
        for child in value.values():
            found = _attachment_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _attachment_key(child)
            if found:
                return found
    return None


def _returned_key(value):
    if isinstance(value, dict):
        for field in ('itemKey', 'key'):
            candidate = value.get(field)
            if isinstance(candidate, str) and re.fullmatch(r'[A-Z0-9]{8}', candidate):
                return candidate
        for child in value.values():
            found = _returned_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _returned_key(child)
            if found:
                return found
    return None


class MCPAdapter:
    """Adapt MCP item/attachment tools to the existing receipt-driven push flow."""

    transport = 'zotero-mcp'

    def __init__(self, mcp, expected_target):
        self.mcp = mcp
        self.expected_target = expected_target
        self.connector = Client()
        self.selection = None
        self.last_item_key = None
        self.last_attachment_key = None

    def resolve_selected(self):
        if self.selection and not self.expected_target.startswith('C'):
            return self.expected_target, self.selection
        libraries, targets = self.mcp.inventory()
        target = self.expected_target
        if re.fullmatch(r'M\d+:[A-Z0-9]{8}', target):
            lib_id_text, collection_key = target[1:].split(':', 1)
            library_id = int(lib_id_text)
            matches = [row for row in targets if row.get('libraryID') == library_id and row.get('collectionKey') == collection_key]
            if len(matches) != 1:
                raise RuntimeError('MCP target not found; run --list and select a listed target')
            match = matches[0]
            self.selection = {'libraryID': library_id, 'name': match['name'], 'collectionKey': collection_key,
                              'libraryEditable': match.get('libraryEditable'),
                              'filesEditable': match.get('filesEditable'),
                              'editable': match.get('libraryEditable'),
                              'canonicalTarget': target}
            return target, self.selection
        if target.startswith('C'):
            code, connector_data = self.connector.request('getSelectedCollection')
            if code != 200 or not isinstance(connector_data, dict):
                raise RuntimeError('Cannot map the selected Connector collection to Zotero MCP')
            connector_target = 'C' + str(connector_data['id']) if connector_data.get('id') is not None else 'L' + str(connector_data['libraryID'])
            if connector_target != target:
                raise RuntimeError('Zotero selection changed or differs from --expect-target; select ' + target)
            library_id = int(connector_data['libraryID'])
            matches = [row for row in targets if row.get('type') == 'collection' and row.get('libraryID') == library_id and row.get('name') == connector_data.get('name')]
            if len(matches) != 1:
                raise RuntimeError('Selected collection is ambiguous or missing in Zotero MCP; use its M<libraryID>:<collectionKey> target from --list')
            match = matches[0]
            canonical_target = f'M{library_id}:{match["collectionKey"]}'
            library = next((row for row in libraries if int(row.get('libraryID', -1)) == library_id), {})
            editable = _combined_permission(
                connector_data.get('libraryEditable'), connector_data.get('editable'),
                match.get('libraryEditable'), match.get('editable'),
                library.get('libraryEditable'), library.get('editable'))
            files_editable = _combined_permission(
                connector_data.get('filesEditable'), match.get('filesEditable'),
                library.get('filesEditable'))
            self.selection = dict(connector_data, collectionKey=match['collectionKey'],
                                  canonicalTarget=canonical_target, libraryEditable=editable,
                                  editable=editable, filesEditable=files_editable)
            return target, self.selection
        if target.startswith('L') and target[1:].isdigit():
            library_id = int(target[1:])
            match = next((row for row in libraries if int(row.get('libraryID', -1)) == library_id), None)
            if not match:
                raise RuntimeError('Zotero MCP library target not found; run --list')
            self.selection = {'libraryID': library_id,
                              'libraryEditable': match.get('libraryEditable'),
                              'filesEditable': match.get('filesEditable'),
                              'editable': match.get('libraryEditable'),
                              'name': match.get('name', ''),
                              'canonicalTarget': target}
            return target, self.selection
        raise RuntimeError('Unsupported Zotero target; use C<id>, L<libraryID>, or M<libraryID>:<collectionKey>')

    def request(self, endpoint, data=None, blob=None, metadata=None):
        try:
            if endpoint == 'saveItems':
                self.last_item_key = None
                item = (data or {}).get('items', [{}])[0]
                target, selection = self.resolve_selected()
                fields = {key: value for key, value in item.items()
                          if key not in ('id', 'itemType', 'creators', 'tags', 'attachments') and isinstance(value, str)}
                result = self.mcp.call('write_item', {
                    'libraryID': selection['libraryID'], 'action': 'create',
                    'itemType': item.get('itemType', 'journalArticle'), 'fields': fields,
                    'creators': item.get('creators', []),
                    'tags': [tag.get('tag', '') for tag in item.get('tags', []) if isinstance(tag, dict)],
                })
                key = _returned_key(result)
                self.last_item_key = key
                if not key:
                    return 0, {'error': 'item_created_but_mcp_key_unconfirmed'}
                if selection.get('collectionKey'):
                    self.mcp.call('add_items_to_collection', {
                        'libraryID': selection['libraryID'], 'collectionKey': selection['collectionKey'], 'itemKeys': [key]})
                return 201, {'itemKey': key, 'target': target}
            if endpoint.startswith('saveAttachment?'):
                self.last_attachment_key = None
                if not metadata or not metadata.get('parentItemID'):
                    return 400, {'error': 'missing_parent_item_key'}
                path = Path(metadata.get('path', '')).expanduser()
                if not path.is_absolute() or not path.is_file() or path.is_symlink():
                    return 400, {'error': 'invalid_local_pdf_path'}
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if sha != metadata.get('sha256'):
                    return 400, {'error': 'local_pdf_changed_before_mcp_import'}
                # The receipt stores the MCP key in parentItemID for this adapter.
                result = self.mcp.call('write_item', {
                    'libraryID': self.resolve_selected()[1]['libraryID'], 'action': 'import',
                    'filePath': str(path),
                    'parentItemKey': metadata['parentItemID'], 'title': metadata.get('title', 'Full Text PDF')})
                key = _attachment_key(result)
                self.last_attachment_key = key
                if not key:
                    return 0, {'error': 'attachment_created_but_mcp_key_unconfirmed'}
                return 201, {'attachmentKey': key}
        except Exception as exc:
            return 0, {'error': 'mcp_write_result_uncertain', 'detail': str(exc)}
        return 400, {'error': 'unsupported_connector_operation'}


def selected(client, expected=None):
    if isinstance(client, MCPAdapter):
        target, data = client.resolve_selected()
        if data.get('libraryEditable') is False or data.get('editable') is False:
            raise RuntimeError('Selected Zotero library/collection is not writable')
        if expected and target != expected:
            raise RuntimeError('Zotero selection changed or differs from --expect-target; select ' + expected)
        return target, data
    code, data = client.request('getSelectedCollection')
    if code != 200 or not isinstance(data, dict) or 'libraryID' not in data:
        raise RuntimeError('Cannot read Zotero target; start desktop Zotero and enable local Connector access')
    target = 'C' + str(data['id']) if data.get('id') is not None else 'L' + str(data['libraryID'])
    if not data.get('libraryEditable') or data.get('editable') is False:
        raise RuntimeError('Selected Zotero library/collection is not writable')
    if expected and target != expected:
        raise RuntimeError('Zotero selection changed or differs from --expect-target; select ' + expected)
    return target, data


@contextmanager
def locked_state(path):
    path = Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.lock')
    if path.is_symlink() or lock.is_symlink():
        raise ValueError('State and lock must not be symlinks')
    try:
        with lock.open('x', encoding='utf-8') as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError('Push already running or stale lock exists; inspect the process before removing the lock')
    try:
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'records': {}}
        validate_state(state)
        def commit():
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('x', encoding='utf-8') as handle:
                    json.dump(state, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        yield state, commit
    finally:
        lock.unlink(missing_ok=True)


def validate_state(state):
    """Reject malformed receipts before a write or a completion claim."""
    if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 1 or not isinstance(state.get('records'), dict):
        raise ValueError('Unsupported Zotero receipt state')
    target_pattern = r'(?:[CL]\d+|M\d+:[A-Z0-9]{8})'
    for key, row in state['records'].items():
        if not isinstance(row, dict) or not re.fullmatch(target_pattern + r':[a-f0-9]{64}', key):
            raise ValueError('Invalid Zotero receipt record')
        if not isinstance(row.get('target'), str) or not re.fullmatch(target_pattern, row['target']):
            raise ValueError('Invalid Zotero receipt target')
        for name in ('metadata', 'pdf'):
            if row.get(name) not in ('pending', 'sending', 'saved', 'uncertain', 'blocked'):
                raise ValueError('Invalid Zotero receipt status: ' + name)
        for name in ('session', 'item_id', 'fingerprint'):
            if not isinstance(row.get(name), str) or not row[name]:
                raise ValueError('Invalid Zotero receipt field: ' + name)
        if not re.fullmatch(r'[a-f0-9]{64}', row['fingerprint']):
            raise ValueError('Invalid Zotero receipt fingerprint')
        for name in ('pdf_sha256', 'mcp_item_key', 'mcp_attachment_key'):
            value = row.get(name)
            pattern = r'[a-f0-9]{64}' if name == 'pdf_sha256' else r'[A-Z0-9]{8}'
            if value is not None and (not isinstance(value, str) or not re.fullmatch(pattern, value)):
                raise ValueError('Invalid Zotero receipt field: ' + name)
        for name in ('aliases', 'target_aliases'):
            values = row.get(name)
            if values is not None and (not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values)):
                raise ValueError('Invalid Zotero receipt aliases: ' + name)
        if any(not re.fullmatch(target_pattern, value) for value in row.get('target_aliases') or []):
            raise ValueError('Invalid Zotero receipt target aliases')
        if 'reconciliation' in row and not isinstance(row['reconciliation'], list):
            raise ValueError('Invalid Zotero reconciliation history')
        for name in ('metadata_transport', 'pdf_transport'):
            if row.get(name) not in (None, 'connector', 'zotero-mcp'):
                raise ValueError('Invalid Zotero receipt transport: ' + name)
        if row['pdf'] in ('sending', 'saved', 'uncertain') and not row.get('pdf_sha256'):
            raise ValueError('Attachment receipt is missing its PDF fingerprint')


def receipt_targets(key, row):
    """Only targets observed together may be used as equivalent destinations."""
    return set(row.get('target_aliases') or []) | {row['target'], key.rsplit(':', 1)[0]}


def receipt_tokens(key, row):
    return set(row.get('aliases') or []) | {'receipt:' + key.rsplit(':', 1)[-1]}


def unmapped_collection(scopes, target, library_id):
    """A legacy MCP collection cannot be equated to a Connector ID by name."""
    return (target.startswith('C') and not any(s.startswith('C') for s in scopes)
            and any(s.startswith('M' + str(library_id) + ':') for s in scopes))


def push(papers, state_path, expected_target, client=None):
    if not isinstance(papers, list) or not papers:
        raise ValueError('Supply a non-empty array of papers')
    client = client or Client()
    prepared = [prepare(p) for p in papers]  # Validate the full set before the first write.
    unique = {}
    alias_index = {}
    for paper in prepared:
        matches = {alias_index[a] for a in paper['aliases'] if a in alias_index}
        if len(matches) > 1:
            raise ValueError('Multiple input identities match; resolve duplicates')
        key = matches.pop() if matches else paper['identity']
        if key in unique:
            prior = unique[key]
            prior['metadata'] = merge_metadata(prior['metadata'], paper['metadata'])
            if any(prior['item'].get(k) and v and prior['item'][k] != v for k, v in paper['item'].items()) or (prior['pdf'] and paper['pdf'] and prior['pdf']['sha256'] != paper['pdf']['sha256']):
                raise ValueError('Conflicting duplicate metadata or PDF; verify the source')
            for name, value in paper['item'].items():
                if not prior['item'].get(name) and value:
                    prior['item'][name] = value
            prior['fingerprint'] = digest(prior['item'])
            prior['aliases'] = sorted(set(prior['aliases'] + paper['aliases']))
            prior['legacy_keys'] = sorted(set(prior['legacy_keys'] + paper['legacy_keys']))
            if paper['pdf']:
                prior['pdf'] = paper['pdf']
        else:
            unique[key] = paper
        for alias in paper['aliases']:
            alias_index[alias] = key
    target, collection = selected(client, expected_target)
    receipt_target = collection.get('canonicalTarget') or target
    if any(p['pdf'] for p in unique.values()) and collection.get('filesEditable') is not True:
        raise RuntimeError('Target does not confirm file-attachment permission; no items were written')
    results = []
    with locked_state(state_path) as (state, commit):
        receipt_index = {}
        for receipt_key, receipt_row in state['records'].items():
            for token in receipt_tokens(receipt_key, receipt_row):
                receipt_index.setdefault(token, set()).add(receipt_key)
        for paper in unique.values():
            targets = {target, receipt_target}
            key = receipt_target + ':' + paper['identity']
            possible, unmapped = set(), set()
            tokens = set(paper['aliases']) | {'receipt:' + value for value in paper['legacy_keys'] + [paper['identity']]}
            candidates = set().union(*(receipt_index.get(token, set()) for token in tokens))
            for candidate_key in candidates:
                scopes = receipt_targets(candidate_key, state['records'][candidate_key])
                if scopes & targets:
                    possible.add(candidate_key)
                elif unmapped_collection(scopes, target, collection['libraryID']):
                    unmapped.add(candidate_key)
            if unmapped:
                results.append({'key': key, 'status': 'blocked',
                                'reason': 'Existing MCP collection receipt has no verified Connector mapping; resume with MCP before changing transport'})
                continue
            if len(possible) > 1:
                results.append({'key': key, 'status': 'blocked', 'reason': 'Multiple receipts match; reconcile manually'})
                continue
            if possible:
                key = possible.pop()
            row = state['records'].get(key)
            if row and any(
                {a for a in row.get('aliases') or [] if a.startswith(prefix)} and
                {a for a in paper['aliases'] if a.startswith(prefix)} and
                not ({a for a in row.get('aliases') or [] if a.startswith(prefix)} &
                     {a for a in paper['aliases'] if a.startswith(prefix)})
                for prefix in ('doi:', 'cnki:')
            ):
                results.append({'key': key, 'status': 'blocked', 'reason': 'Conflicting strong identifiers; verify existing item'})
                continue
            if row and row['fingerprint'] != paper['fingerprint']:
                results.append({'key': key, 'status': 'blocked', 'reason': 'Metadata changed; reconcile existing item manually'})
                continue
            if row is None:
                row = {'aliases': paper['aliases'], 'fingerprint': paper['fingerprint'], 'target': receipt_target,
                       'session': uuid.uuid4().hex, 'item_id': uuid.uuid4().hex,
                       'metadata': 'pending', 'pdf': 'pending', 'pdf_sha256': None,
                       'mcp_item_key': None, 'mcp_attachment_key': None}
                state['records'][key] = row
            else:
                # Keep returned receipt keys stable for --resolve. Persist the
                # canonical target and aliases even when no network write follows.
                row['aliases'] = sorted(set((row.get('aliases') or []) + paper['aliases']))
            row['target_aliases'] = sorted(receipt_targets(key, row) | targets)
            if receipt_target.startswith('M'):
                row['target'] = receipt_target
            for token in receipt_tokens(key, row):
                receipt_index.setdefault(token, set()).add(key)
            commit()
            if row['metadata'] in ('sending', 'uncertain'):
                results.append({'key': key, 'status': 'uncertain', 'reason': 'Check Zotero before resolving an uncertain metadata write'})
                continue
            if row['metadata'] == 'blocked':
                results.append({'key': key, 'status': 'blocked',
                                'reason': 'Resolve the blocked metadata receipt after checking Zotero'})
                continue
            if row['metadata'] == 'pending':
                selected(client, target)
                row['metadata'] = 'sending'
                row['metadata_transport'] = getattr(client, 'transport', 'connector')
                commit()
                item = dict(paper['item'], id=row['item_id'])
                code, reply = client.request('saveItems', {'sessionID': row['session'], 'uri': item.get('url', ''), 'items': [item]})
                if getattr(client, 'transport', '') == 'zotero-mcp' and client.last_item_key:
                    row['mcp_item_key'] = client.last_item_key
                row['metadata'] = 'saved' if code == 201 else 'uncertain'
                row['last_metadata_http'] = code
                commit()
                if code != 201:
                    results.append({'key': key, 'status': 'uncertain', 'http': code,
                                    'reason': (reply.get('detail') or reply.get('error')) if isinstance(reply, dict) and (reply.get('detail') or reply.get('error')) else 'No confirmed save receipt; 409 is not library deduplication'})
                    continue
                try:
                    selected(client, target)
                except RuntimeError:
                    row['metadata'] = 'uncertain'
                    commit()
                    raise
            pdf = paper['pdf']
            if pdf:
                if row.get('pdf_sha256') and row['pdf_sha256'] != pdf['sha256']:
                    results.append({'key': key, 'status': 'blocked', 'reason': 'PDF changed; check the existing attachment'})
                    continue
                if row['pdf'] == 'blocked':
                    results.append({'key': key, 'status': 'blocked', 'metadata': 'saved',
                                    'reason': 'Resolve the rejected attachment after checking Zotero; do not resend automatically'})
                    continue
                if row['pdf'] in ('sending', 'uncertain'):
                    results.append({'key': key, 'status': 'uncertain', 'metadata': 'saved', 'reason': 'Check the attachment before retrying'})
                    continue
                if row['pdf'] != 'saved':
                    if getattr(client, 'transport', '') == 'zotero-mcp' and not row.get('mcp_item_key'):
                        results.append({'key': key, 'status': 'blocked', 'metadata': 'saved',
                                        'reason': 'This receipt predates Zotero MCP item keys; rerun explicitly with --transport connector or reconcile the existing item first'})
                        continue
                    parent_transport = row.get('metadata_transport') or (
                        'connector' if key.startswith('C') else
                        'zotero-mcp' if row.get('mcp_item_key') or row['target'].startswith('M') else 'connector')
                    if getattr(client, 'transport', 'connector') != 'zotero-mcp' and parent_transport == 'zotero-mcp':
                        results.append({'key': key, 'status': 'blocked', 'metadata': 'saved',
                                        'reason': 'MCP-created parent has no Connector session; resume its attachment with MCP'})
                        continue
                    _, col = selected(client, target)
                    if col.get('filesEditable') is not True:
                        raise RuntimeError('Target no longer confirms file-attachment permission')
                    pdf_bytes = None
                    if getattr(client, 'transport', '') != 'zotero-mcp':
                        pdf_bytes = Path(pdf['path']).read_bytes()
                        if hashlib.sha256(pdf_bytes).hexdigest() != pdf['sha256']:
                            raise ValueError('PDF changed after input validation; re-open and verify the file')
                    row.update(pdf='sending', pdf_sha256=pdf['sha256'])
                    row['pdf_transport'] = getattr(client, 'transport', 'connector')
                    commit()
                    url = paper['item'].get('url') or pdf_path_uri(pdf['path'])
                    code, reply = client.request('saveAttachment?sessionID=' + row['session'], blob=pdf_bytes,
                                                metadata={'parentItemID': row.get('mcp_item_key') if getattr(client, 'transport', '') == 'zotero-mcp' else row['item_id'],
                                                          'path': pdf['path'], 'sha256': pdf['sha256'],
                                                          'title': 'Full Text PDF', 'url': url})
                    # Only explicit session/permission rejection is safe to retry after resolving its cause.
                    rejected = code == 200 or (code == 400 and isinstance(reply, dict) and reply.get('error') == 'SESSION_NOT_FOUND')
                    if getattr(client, 'transport', '') == 'zotero-mcp' and getattr(client, 'last_attachment_key', None):
                        row['mcp_attachment_key'] = client.last_attachment_key
                    row['pdf'] = 'saved' if code == 201 else ('blocked' if rejected else 'uncertain')
                    row['last_pdf_http'] = code
                    commit()
                if row['pdf'] != 'saved':
                    results.append({'key': key, 'status': row['pdf'], 'metadata': 'saved',
                                    'reason': 'PDF not saved; if session expired, attach locally to the existing Zotero item'})
                    continue
            results.append({'key': key, 'status': 'saved', 'metadata': 'saved', 'pdf': 'saved' if pdf else 'not_requested'})
    return {'transport': getattr(client, 'transport', 'connector'), 'target': target,
            'results': results, 'complete': all(r['status'] == 'saved' for r in results)}


def pdf_path_uri(path):
    # Local provenance only; the script never asks Zotero to fetch this URI.
    return Path(path).as_uri()


def resolve(state_path, key, stage, outcome, note, item_key=None):
    if stage not in ('metadata', 'pdf') or outcome not in ('saved', 'not-saved'):
        raise ValueError('Invalid reconciliation stage or outcome')
    if not isinstance(note, str) or not note.strip():
        raise ValueError('Reconciliation requires a non-empty verification note')
    if item_key is not None:
        if not isinstance(item_key, str) or not re.fullmatch(r'[A-Z0-9]{8}', item_key):
            raise ValueError('--item-key must be an 8-character MCP item key')
        if stage != 'metadata' or outcome != 'saved':
            raise ValueError('--item-key is only valid with --stage metadata --outcome saved')
    with locked_state(state_path) as (state, commit):
        row = state['records'][key]
        backfill = stage == 'metadata' and outcome == 'saved' and item_key and row[stage] == 'saved'
        if row[stage] not in ('sending', 'uncertain', 'blocked') and not backfill:
            raise ValueError('Only an uncertain/blocked write may be manually reconciled')
        if item_key and row.get('mcp_item_key') and row['mcp_item_key'] != item_key:
            raise ValueError('Conflicting MCP item key; verify the existing receipt')
        detail = {'stage': stage, 'outcome': outcome, 'note': note}
        if item_key:
            detail['item_key'] = item_key
        if outcome == 'not-saved':
            detail['previous'] = {name: row.get(name) for name in (
                'metadata', 'pdf', 'session', 'item_id', 'mcp_item_key',
                'mcp_attachment_key', 'pdf_sha256', 'metadata_transport', 'pdf_transport')}
        row.setdefault('reconciliation', []).append(detail)
        row[stage] = 'saved' if outcome == 'saved' else 'pending'
        if stage == 'metadata' and outcome == 'saved' and item_key:
            row['mcp_item_key'] = item_key
        if stage == 'metadata' and outcome == 'not-saved':
            row.update(session=uuid.uuid4().hex, item_id=uuid.uuid4().hex,
                       pdf='pending', pdf_sha256=None, mcp_item_key=None,
                       mcp_attachment_key=None, metadata_transport=None, pdf_transport=None)
        elif stage == 'pdf' and outcome == 'not-saved':
            row.update(pdf_sha256=None, mcp_attachment_key=None, pdf_transport=None)
        commit()


def mcp_listing(mcp):
    libraries, targets = mcp.inventory()
    result = {'transport': 'zotero-mcp', 'libraries': libraries, 'targets': targets}
    code, current = Client().request('getSelectedCollection')
    if code == 200 and isinstance(current, dict) and current.get('libraryID') is not None:
        legacy = 'C' + str(current['id']) if current.get('id') is not None else 'L' + str(current['libraryID'])
        result['target'] = legacy
        result['selected'] = current
        if current.get('id') is not None:
            matches = [row for row in targets if row.get('type') == 'collection'
                       and row.get('libraryID') == int(current['libraryID']) and row.get('name') == current.get('name')]
            if len(matches) == 1:
                result['mcpTarget'] = matches[0]['target']
            else:
                result['targetMapping'] = 'ambiguous_or_missing; use a listed M<libraryID>:<collectionKey> target'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', help='UTF-8 JSON paper object or array')
    parser.add_argument('--list', action='store_true', help='Read Zotero libraries and collections (MCP first)')
    parser.add_argument('--transport', choices=['auto', 'mcp', 'connector'], default='auto',
                        help='Prefer Zotero MCP; auto falls back to Connector only if MCP is unavailable before a write')
    parser.add_argument('--state', type=Path, help='Persistent receipt JSON outside the source repository')
    parser.add_argument('--expect-target', help='Target from --list: C<id>, L<libraryID>, or M<libraryID>:<collectionKey>')
    parser.add_argument('--dry-run', action='store_true', help='Validate input locally without contacting Zotero')
    parser.add_argument('--resolve', metavar='RECORD_KEY', help='Reconcile only after checking the real Zotero item')
    parser.add_argument('--stage', choices=['metadata', 'pdf'])
    parser.add_argument('--outcome', choices=['saved', 'not-saved'])
    parser.add_argument('--note', help='Evidence from manual Zotero verification')
    parser.add_argument('--item-key', help='Confirmed 8-character Zotero MCP item key for --resolve metadata')
    args = parser.parse_args()
    mcp = None
    try:
        if args.list:
            if args.transport != 'connector':
                try:
                    mcp = ZoteroMCP()
                    listing = mcp_listing(mcp)
                except (MCPUnavailable, MCPError, OSError, RuntimeError):
                    if mcp:
                        mcp.close()
                        mcp = None
                    if args.transport == 'mcp':
                        raise
                if mcp:
                    print(json.dumps(listing, ensure_ascii=False, indent=2))
                    return 0
            target, data = selected(Client())
            print(json.dumps({'transport': 'connector', 'target': target, **data}, ensure_ascii=False, indent=2))
            return 0
        if args.resolve:
            if not (args.state and args.stage and args.outcome and args.note):
                parser.error('--resolve requires --state, --stage, --outcome and --note')
            resolve(args.state, args.resolve, args.stage, args.outcome, args.note, args.item_key)
            print(json.dumps({'reconciled': args.resolve}, ensure_ascii=False))
            return 0
        if not args.input:
            parser.error('Supply input JSON or --list')
        data = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        papers = data if isinstance(data, list) else [data]
        if not papers:
            raise ValueError('No papers supplied')
        if args.dry_run:
            ready = [prepare(p) for p in papers]
            print(json.dumps({'valid_records': len(ready), 'local_pdfs': sum(bool(p['pdf']) for p in ready)}, ensure_ascii=False))
            return 0
        if not (args.state and args.expect_target):
            parser.error('Push requires --state and --expect-target from --list')
        client = None
        if args.transport != 'connector':
            try:
                mcp = ZoteroMCP()
                client = MCPAdapter(mcp, args.expect_target)
            except MCPUnavailable:
                if args.transport == 'mcp':
                    raise
        if client is None:
            client = Client()
        result = push(papers, args.state, args.expect_target, client=client)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['complete'] else 2
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if mcp:
            mcp.close()


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    sys.exit(main())
