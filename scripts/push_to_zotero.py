#!/usr/bin/env python3
"""Save verified CNKI metadata and local PDFs to the local Zotero Connector.

Independent implementation informed by cookjohn/cnki-skills. No CNKI network
requests, cookies, cloud API keys, or automatic retries after uncertain writes.
"""
import argparse
from contextlib import contextmanager
import hashlib
import html
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
from common import aliases, legacy_identities, merge_metadata, source_url

API = 'http://127.0.0.1:23119/connector/'


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
            with self.opener.open(req, timeout=60 if blob is not None else 15) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, {'error': 'connection_error_or_timeout'}
        try:
            return status, json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return status, {'error': 'non_json_response'}


def selected(client, expected=None):
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
        if state.get('version') != 1 or not isinstance(state.get('records'), dict):
            raise ValueError('Unsupported Zotero receipt state')
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
        lock.unlink()


def push(papers, state_path, expected_target, client=None):
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
    if any(p['pdf'] for p in unique.values()) and not collection.get('filesEditable', False):
        raise RuntimeError('Target does not support file attachments; no items were written')
    results = []
    with locked_state(state_path) as (state, commit):
        for paper in unique.values():
            key = target + ':' + paper['identity']
            possible = set()
            for candidate in paper['legacy_keys']:
                candidate_key = target + ':' + candidate
                if candidate_key in state['records']:
                    possible.add(candidate_key)
            for candidate_key, candidate_row in state['records'].items():
                if candidate_row.get('target') == target and set(candidate_row.get('aliases', [])) & set(paper['aliases']):
                    possible.add(candidate_key)
            if len(possible) > 1:
                results.append({'key': key, 'status': 'blocked', 'reason': 'Multiple receipts match; reconcile manually'})
                continue
            if possible:
                key = possible.pop()
            row = state['records'].get(key)
            if row and any(
                {a for a in row.get('aliases', []) if a.startswith(prefix)} and
                {a for a in paper['aliases'] if a.startswith(prefix)} and
                not ({a for a in row.get('aliases', []) if a.startswith(prefix)} &
                     {a for a in paper['aliases'] if a.startswith(prefix)})
                for prefix in ('doi:', 'cnki:')
            ):
                results.append({'key': key, 'status': 'blocked', 'reason': 'Conflicting strong identifiers; verify existing item'})
                continue
            if row and row['fingerprint'] != paper['fingerprint']:
                results.append({'key': key, 'status': 'blocked', 'reason': 'Metadata changed; reconcile existing item manually'})
                continue
            if row is None:
                row = {'aliases': paper['aliases'], 'fingerprint': paper['fingerprint'], 'target': target,
                       'session': uuid.uuid4().hex, 'item_id': uuid.uuid4().hex,
                       'metadata': 'pending', 'pdf': 'pending', 'pdf_sha256': None}
                state['records'][key] = row
            if row['metadata'] in ('sending', 'uncertain'):
                results.append({'key': key, 'status': 'uncertain', 'reason': 'Check Zotero before resolving an uncertain metadata write'})
                continue
            if row['metadata'] == 'pending':
                selected(client, target)
                row['metadata'] = 'sending'
                commit()
                item = dict(paper['item'], id=row['item_id'])
                code, _ = client.request('saveItems', {'sessionID': row['session'], 'uri': item.get('url', ''), 'items': [item]})
                row['metadata'] = 'saved' if code == 201 else 'uncertain'
                row['last_metadata_http'] = code
                commit()
                if code != 201:
                    results.append({'key': key, 'status': 'uncertain', 'http': code,
                                    'reason': 'No confirmed save receipt; 409 is not library deduplication'})
                    continue
                try:
                    selected(client, target)
                except RuntimeError:
                    row['metadata'] = 'uncertain'
                    commit()
                    raise
            pdf = paper['pdf']
            if pdf:
                if row['pdf_sha256'] and row['pdf_sha256'] != pdf['sha256']:
                    results.append({'key': key, 'status': 'blocked', 'reason': 'PDF changed; check the existing attachment'})
                    continue
                if row['pdf'] in ('sending', 'uncertain'):
                    results.append({'key': key, 'status': 'uncertain', 'metadata': 'saved', 'reason': 'Check the attachment before retrying'})
                    continue
                if row['pdf'] != 'saved':
                    _, col = selected(client, target)
                    if not col.get('filesEditable', False):
                        raise RuntimeError('Target no longer supports file attachments')
                    pdf_bytes = Path(pdf['path']).read_bytes()
                    if hashlib.sha256(pdf_bytes).hexdigest() != pdf['sha256']:
                        raise ValueError('PDF changed after input validation; re-open and verify the file')
                    row.update(pdf='sending', pdf_sha256=pdf['sha256'])
                    commit()
                    url = paper['item'].get('url') or pdf_path_uri(pdf['path'])
                    code, reply = client.request('saveAttachment?sessionID=' + row['session'], blob=pdf_bytes,
                                                metadata={'parentItemID': row['item_id'], 'title': 'Full Text PDF', 'url': url})
                    # Only explicit session/permission rejection is safe to retry after resolving its cause.
                    rejected = code == 200 or (code == 400 and isinstance(reply, dict) and reply.get('error') == 'SESSION_NOT_FOUND')
                    row['pdf'] = 'saved' if code == 201 else ('blocked' if rejected else 'uncertain')
                    row['last_pdf_http'] = code
                    commit()
                if row['pdf'] != 'saved':
                    results.append({'key': key, 'status': row['pdf'], 'metadata': 'saved',
                                    'reason': 'PDF not saved; if session expired, attach locally to the existing Zotero item'})
                    continue
            results.append({'key': key, 'status': 'saved', 'metadata': 'saved', 'pdf': 'saved' if pdf else 'not_requested'})
    return {'target': target, 'results': results, 'complete': all(r['status'] == 'saved' for r in results)}


def pdf_path_uri(path):
    # Local provenance only; the script never asks Zotero to fetch this URI.
    return Path(path).as_uri()


def resolve(state_path, key, stage, outcome, note):
    with locked_state(state_path) as (state, commit):
        row = state['records'][key]
        if row[stage] not in ('sending', 'uncertain', 'blocked'):
            raise ValueError('Only an uncertain/blocked write may be manually reconciled')
        row.setdefault('reconciliation', []).append({'stage': stage, 'outcome': outcome, 'note': note})
        row[stage] = 'saved' if outcome == 'saved' else 'pending'
        if stage == 'metadata' and outcome == 'not-saved':
            row.update(session=uuid.uuid4().hex, item_id=uuid.uuid4().hex, pdf='pending', pdf_sha256=None)
        commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', nargs='?', help='UTF-8 JSON paper object or array')
    parser.add_argument('--list', action='store_true', help='Read selected target and available collections')
    parser.add_argument('--state', type=Path, help='Persistent receipt JSON outside the source repository')
    parser.add_argument('--expect-target', help='Observed C<collectionID> or L<libraryID> from --list')
    parser.add_argument('--dry-run', action='store_true', help='Validate input locally without contacting Zotero')
    parser.add_argument('--resolve', metavar='RECORD_KEY', help='Reconcile only after checking the real Zotero item')
    parser.add_argument('--stage', choices=['metadata', 'pdf'])
    parser.add_argument('--outcome', choices=['saved', 'not-saved'])
    parser.add_argument('--note', help='Evidence from manual Zotero verification')
    args = parser.parse_args()
    try:
        if args.list:
            target, data = selected(Client())
            print(json.dumps({'target': target, **data}, ensure_ascii=False, indent=2))
            return 0
        if args.resolve:
            if not (args.state and args.stage and args.outcome and args.note):
                parser.error('--resolve requires --state, --stage, --outcome and --note')
            resolve(args.state, args.resolve, args.stage, args.outcome, args.note)
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
        result = push(papers, args.state, args.expect_target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['complete'] else 2
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    sys.exit(main())
