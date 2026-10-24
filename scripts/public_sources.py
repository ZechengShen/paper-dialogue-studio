"""Bounded public fetching with DNS-pinned connections and redirect validation."""
from __future__ import annotations
import ipaddress
import json
import re
import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urljoin, urlparse

import certifi
import urllib3


def public_address(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('仅支持不含账号密码的公开 HTTP/HTTPS 地址。')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port not in (80, 443):
        raise ValueError('远程读取仅支持标准 HTTP/HTTPS 端口。')
    host = parsed.hostname.encode('idna').decode('ascii')
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('拒绝访问本机、内网、保留地址或混合 DNS 结果。')
    return parsed, host, port, addresses[0][4][0]


def request_public(url, method='GET', headers=None, body=None, timeout=40, limit=16*1024*1024):
    parsed, host, port, address = public_address(url)
    options = {'port': port, 'timeout': urllib3.Timeout(connect=10, read=timeout), 'retries': False}
    if parsed.scheme == 'https':
        pool = urllib3.HTTPSConnectionPool(address, assert_hostname=host, server_hostname=host,
                                          cert_reqs='CERT_REQUIRED', ca_certs=certifi.where(), **options)
    else:
        pool = urllib3.HTTPConnectionPool(address, **options)
    response = None
    try:
        response = pool.request(method, (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
            headers={**(headers or {}), 'Host': host, 'User-Agent': 'PaperDialogue/3.1', 'Accept-Encoding': 'identity'},
            body=body, redirect=False, preload_content=False)
        chunks, size = [], 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('远程响应超出大小上限，请下载后分开上传。')
            chunks.append(chunk)
        return response.status, dict(response.headers), b''.join(chunks)
    except urllib3.exceptions.HTTPError as exc:
        raise OSError('远程连接失败；未记录请求密钥或响应正文。') from exc
    finally:
        if response:
            response.close()
        pool.close()


def fetch_document(url, transport=None):
    transport = transport or request_public
    for _ in range(5):
        status, headers, raw = transport(url)
        lower = {k.lower(): v for k, v in headers.items()}
        if status in (301, 302, 303, 307, 308):
            if not lower.get('location'):
                raise ValueError('远程链接缺少重定向目标。')
            url = urljoin(url, lower['location'])
            continue  # Every destination is resolved and pinned anew. No credentials forwarded.
        if status != 200:
            raise ValueError(f'原文链接返回 HTTP {status}。')
        return raw, lower.get('content-type', ''), url
    raise ValueError('原文链接重定向过多。')


def notion_document(url, token, transport=None):
    transport = transport or request_public
    host = (urlparse(url).hostname or '').lower()
    if not (host in ('notion.so', 'notion.site') or host.endswith(('.notion.so', '.notion.site'))):
        raise ValueError('Notion Token 仅用于 Notion 页面。')
    found = re.search(r'([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})(?:$|[/?#])', url)
    if not found:
        raise ValueError('无法识别 Notion Page ID，请复制包含页面 ID 的分享链接。')
    headers = {'Authorization': 'Bearer ' + token, 'Notion-Version': '2022-06-28'}
    blocks, links, calls, visited = [], [], 0, set()
    def children(block_id, depth=0):
        nonlocal calls
        if depth > 12 or block_id in visited:
            raise ValueError('Notion 层级过深或循环，未静默截断内容。')
        visited.add(block_id)
        cursor = None
        while True:
            calls += 1
            if calls > 60:
                raise ValueError('Notion 页面超过 60 次读取上限，请按子页面分开导入。')
            query = urlencode({'page_size': 100, **({'start_cursor': cursor} if cursor else {})})
            status, _, raw = transport(f'https://api.notion.com/v1/blocks/{block_id}/children?{query}', headers=headers)
            if status != 200:
                raise ValueError(f'Notion 返回 {status}，请检查 Token，并将页面共享给对应 Integration。')
            data = json.loads(raw)
            for item in data.get('results', []):
                kind = item.get('type', '')
                content = item.get(kind, {})
                rich = content.get('rich_text', [])
                text = ''.join(part.get('plain_text') or part.get('text', {}).get('content', '') for part in rich)
                if kind == 'equation':
                    text = content.get('expression', '')
                if kind == 'table_row':
                    text = ' | '.join(''.join(p.get('plain_text', '') for p in cell) for cell in content.get('cells', []))
                if kind in ('bookmark', 'embed', 'link_preview'):
                    text = content.get('url', '')
                    links.append({'label': kind, 'url': text})
                links.extend({'label': p.get('plain_text', ''), 'url': p['href']} for p in rich if p.get('href'))
                if text:
                    blocks.append({'location': item['id'], 'kind': kind, 'text': text})
                elif kind in ('image', 'pdf', 'child_page', 'child_database', 'unsupported'):
                    blocks.append({'location': item['id'], 'kind': kind, 'text': '[需单独读取的非正文块：' + kind + ']'} )
                if item.get('has_children') and kind not in ('child_page', 'child_database'):
                    children(item['id'], depth+1)
            if not data.get('has_more'):
                break
            cursor = data.get('next_cursor')
            if not cursor:
                raise ValueError('Notion 分页不完整。')
    children(found.group(1).replace('-', ''))
    return {'title': 'Notion 研究材料', 'blocks': blocks, 'links': links, 'images': [],
            'warnings': ['Notion 图片、附件、子页面及数据库需单独提供；本次仅读取当前页面文本块。']}


def search_arxiv(title, transport=None):
    """Return metadata candidates, never call a title match a verified paper."""
    transport = transport or request_public
    query = 'ti:"' + re.sub(r'["\n\r]', ' ', title[:300]) + '"'
    url = 'https://export.arxiv.org/api/query?' + urlencode({'search_query': query, 'max_results': 3})
    status, _, raw = transport(url)
    if status != 200:
        return {'query': query, 'status': 'unavailable', 'candidates': []}
    root = ET.fromstring(raw)
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    candidates = []
    for entry in root.findall('a:entry', ns):
        candidates.append({'title': entry.findtext('a:title', '', ns).strip(),
            'authors': [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)],
            'year': entry.findtext('a:published', '', ns)[:4],
            'url': entry.findtext('a:id', '', ns).replace('http://', 'https://'),
            'pdf_url': next((a.get('href', '').replace('http://', 'https://') for a in entry.findall('a:link', ns) if a.get('title') == 'pdf'), '')})
    return {'query': query, 'status': 'candidates_found' if candidates else 'not_found', 'candidates': candidates}
