"""Shared metadata identity and URL validation (stdlib only)."""
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit


def doi(value):
    if not isinstance(value, str):
        raise ValueError('DOI must be text')
    value = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', value.strip(), flags=re.I).lower()
    if value and not re.fullmatch(r'10\.\d{4,9}/\S+', value):
        raise ValueError('Invalid DOI')
    return value


def source_url(value, allow_proxy=True):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('URL must be non-empty text')
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None or p.fragment:
        raise ValueError('Use an http(s) source URL without credentials or fragments')
    sensitive = r'token|ticket|session|password|cookie|authorization|saml|signature|(?:^|[_-])auth(?:$|[_-])'
    # Decode before parsing, including encoded separators and nested encoding.
    decoded = value
    for _ in range(8):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if unquote(decoded) != decoded:
        raise ValueError('Excessively encoded source URL')
    parts = urlsplit(decoded)
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise ValueError('Encoded credentials/fragments are not accepted')
    if any(re.search(sensitive, key, re.I) for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError('Do not persist session-bearing URLs')
    if re.search(r'(?:token|ticket|session|password|cookie|authorization|signature|auth)[=/]', parts.path, re.I):
        raise ValueError('Do not persist authentication paths')
    if not allow_proxy and (p.hostname == 'vpn.htu.edu.cn' or p.hostname.endswith('.vpn.htu.edu.cn')):
        raise ValueError('Use an observed public URL/DOI, or omit the campus proxy URL')
    return value


def evidence_source(value):
    if value.startswith(('http:', 'https:')):
        return source_url(value)
    if not Path(value).is_absolute():
        raise ValueError('Evidence source must be a source URL or absolute local path')
    return value


def aliases(rec):
    result = []
    normalized = doi(rec.get('doi') or '')
    if normalized:
        result.append('doi:' + normalized)
    cnki = rec.get('cnki_id')
    if cnki is not None and (not isinstance(cnki, str) or not cnki.strip()):
        raise ValueError('cnki_id must be non-empty text')
    if rec.get('database') and rec.get('record_id'):
        if any(not isinstance(rec[k], str) or not rec[k].strip() for k in ('database', 'record_id')):
            raise ValueError('database and record_id must be non-empty text')
        observed = rec['database'].strip() + ':' + rec['record_id'].strip()
        if cnki and cnki != observed:
            raise ValueError('Conflicting CNKI identifiers')
        cnki = observed
    if cnki:
        result.append('cnki:' + cnki)
    if rec.get('url'):
        result.append('url:' + hashlib.sha256(source_url(rec['url']).encode()).hexdigest()[:24])
    return result


def merge_metadata(old, new):
    if doi(old.get('doi') or '') and doi(new.get('doi') or '') and doi(old['doi']) != doi(new['doi']):
        raise ValueError('Conflicting DOI for the same paper')
    for key in ('title', 'year', 'record_id', 'database', 'cnki_id', 'journal'):
        if old.get(key) and new.get(key) and old[key] != new[key]:
            raise ValueError('Conflicting duplicate metadata: ' + key)
    merged = dict(old)
    if old.get('authors') and new.get('authors') and old['authors'] != new['authors']:
        a, b = old['authors'], new['authors']
        if old.get('authors_complete') is False and new.get('authors_complete') is True and isinstance(a, list) and isinstance(b, list) and b[:len(a)] == a:
            merged.update(authors=b, authors_complete=True)
        elif old.get('authors_complete') is True and new.get('authors_complete') is False and isinstance(a, list) and isinstance(b, list) and a[:len(b)] == b:
            pass  # Never downgrade verified authors with a shorter list.
        else:
            raise ValueError('Conflicting duplicate metadata: authors')
    elif new.get('authors_complete') is True:
        merged['authors_complete'] = True
    for key, value in new.items():
        if not merged.get(key) and value:
            merged[key] = value
    return merged


def legacy_identities(rec):
    """All keys used by v1 Zotero receipts, including the pre-DOI key."""
    result = []
    if rec.get('doi'):
        result.append(('doi', doi(rec['doi'])))
    if rec.get('cnki_id'):
        result.append(('cnki', rec['cnki_id']))
    result.append(('metadata', rec['title'], rec.get('year', ''), rec['journal'], rec['authors']))
    return result
