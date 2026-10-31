import os, re, time, hashlib, tempfile, datetime, threading, base64
from urllib.parse import urlparse, urlencode, urljoin
import requests
from packaging.version import parse as parse_version
from constants import VERSION

class UpdateError(Exception): pass
class SSLTrustState: degraded = False; degraded_reason = None

UPDATER_REVISION = "2026-10-16-signed-v15"
GITHUB_API = "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest"
GITEE_OWNER = "tiankong_mc"
GITEE_REPO = "secure-vault"
GITEE_TOKEN = ""
_gitee_params = {'direction': 'desc', 'per_page': '5'}
if GITEE_TOKEN: _gitee_params['access_token'] = GITEE_TOKEN
GITEE_API = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/releases?{urlencode(_gitee_params)}"
SIGNING_PUBLIC_KEY = "nx697jofj6nw3UZhnJpKixo2E+lbf90pcpisC2v2GRw="

DOWNLOAD_MIRRORS = ["https://ghfast.top/", "https://ghproxy.net/", "https://gh-proxy.com/", "https://gh.llkk.cc/", "https://ghproxy.cc/", "https://ghp.ci/", "https://ghproxy.homeboyc.cn/", ""]
TRUSTED_MIRRORS = ('ghfast.top', 'ghproxy.net', 'gh-proxy.com', 'gh.llkk.cc', 'ghproxy.cc', 'ghp.ci', 'ghproxy.homeboyc.cn')
CHUNK_SIZE = 256 * 1024
CONNECT_TIMEOUT = 15; READ_TIMEOUT = 30
MAX_VERIFY_RESPONSE_SIZE = 4096; MAX_SIGNATURE_SIZE = 1024; MAX_REDIRECTS = 5
TRUSTED_HOSTS = ('github.com', 'gitee.com')
TRUSTED_SUFFIXES = ('.github.com', '.githubusercontent.com', '.gitee.com')

def _is_trusted_host(host):
    h = (host or '').lower()
    if h in TRUSTED_MIRRORS: return True
    return h in TRUSTED_HOSTS or any(h.endswith(s) for s in TRUSTED_SUFFIXES)

def _is_cert_error(exc):
    msg = str(exc).lower()
    return 'certificate verify failed' in msg or 'sslcertverificationerror' in msg

def _parse_tag_safe(tag):
    try: return parse_version(tag)
    except Exception: return None

def is_newer(remote_tag):
    try: return parse_version(remote_tag) > parse_version(VERSION)
    except Exception: return False

def _new_session():
    s = requests.Session(); s.headers.update({'User-Agent': 'SecureVault'}); return s

def _request_strict(session, method, url, **kwargs):
    parsed = urlparse(url)
    if parsed.scheme != 'https': raise UpdateError(f"拒绝非 HTTPS: {url}")
    kwargs.setdefault('timeout', (CONNECT_TIMEOUT, READ_TIMEOUT))
    try: return session.request(method, url, **kwargs)
    except requests.exceptions.SSLError as e1:
        if not _is_cert_error(e1): raise UpdateError(f"网络错误: {e1}")
    try:
        import certifi
        kwargs['verify'] = certifi.where()
        return session.request(method, url, **kwargs)
    except Exception as e: raise UpdateError(f"TLS 校验失败: {e}")

def _get_verified(session, url, *, stream=False, timeout=None, extra_headers=None, max_redirects=MAX_REDIRECTS):
    current = url
    for _ in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme != 'https': raise UpdateError(f"非 HTTPS: {current}")
        if not _is_trusted_host(parsed.hostname): raise UpdateError(f"非受信域名: {parsed.hostname}")
        kwargs = {'stream': stream, 'allow_redirects': False}
        if timeout: kwargs['timeout'] = timeout
        if extra_headers: kwargs['headers'] = extra_headers
        resp = _request_strict(session, 'GET', current, **kwargs)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('Location')
            if not location: return resp
            resp.close(); current = urljoin(current, location); continue
        return resp
    raise UpdateError("重定向次数过多")

def _is_usable_release(data):
    if not isinstance(data, dict): return False
    has_exe = False; has_sig = False
    for a in data.get('assets', []):
        name = (a.get('name') or '').lower()
        if name in ('encryption.exe', 'securevault.exe'): has_exe = True
        if name.endswith('.sig'): has_sig = True
    if not has_exe: return False
    if SIGNING_PUBLIC_KEY and not has_sig: return False
    return True

def get_latest_release(timeout=15):
    gitee, github = None, None
    try:
        resp = _get_verified(_new_session(), GITEE_API, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data: gitee = data[0]
            elif isinstance(data, dict): gitee = data
    except Exception: pass
    try:
        resp = _get_verified(_new_session(), GITHUB_API, timeout=timeout)
        if resp.status_code == 200: github = resp.json()
    except Exception: pass
    if gitee and not _is_usable_release(gitee): gitee = None
    if github and not _is_usable_release(github): github = None
    if not gitee and not github: raise UpdateError("未找到可用更新源")
    if not gitee: return github
    if not github: return gitee
    gt, ght = gitee.get('tag_name', ''), github.get('tag_name', '')
    if _parse_tag_safe(ght) and _parse_tag_safe(gt) and _parse_tag_safe(ght) > _parse_tag_safe(gt): return github
    return gitee

def find_exe_asset(release_data):
    for a in release_data.get('assets', []):
        if (a.get('name') or '').lower() in ('encryption.exe', 'securevault.exe'):
            return {'browser_download_url': a['browser_download_url'], 'name': a['name']}
    return None

def find_signature_asset(release_data):
    exe = find_exe_asset(release_data)
    if not exe: return None
    wanted = exe['name'].lower() + '.sig'
    for a in release_data.get('assets', []):
        if (a.get('name') or '').lower() == wanted:
            return {'browser_download_url': a['browser_download_url'], 'name': a['name']}
    return None

def extract_sha256(release_data):
    # 优先取 asset 的 digest 字段（GitHub API 会提供 sha256:...）
    for a in release_data.get('assets', []):
        digest = a.get('digest') or ''
        m = re.fullmatch(r'sha256:([a-fA-F0-9]{64})', digest.strip(), re.IGNORECASE)
        if m: return m.group(1).lower()
    # 否则取 body 中最后一个 64-hex（发布说明可能包含多个哈希，最后一个通常是 exe）
    text = re.sub(r'[*_`~\\]', '', release_data.get('body', '') or '')
    matches = re.findall(r'[a-fA-F0-9]{64}', text)
    return matches[-1].lower() if matches else None

def download_signature(url, timeout=15):
    resp = _get_verified(_new_session(), url, stream=True, timeout=timeout)
    chunks, total = [], 0
    try:
        for chunk in resp.iter_content(chunk_size=512):
            total += len(chunk)
            if total > MAX_SIGNATURE_SIZE: raise UpdateError("签名过大")
            chunks.append(chunk)
        return b''.join(chunks)
    finally: resp.close()

def _verify_ed25519(signature, message, public_key_b64):
    if len(signature) != 64: raise UpdateError("签名长度错误")
    raw = base64.b64decode(public_key_b64.strip(), validate=True)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pk = Ed25519PublicKey.from_public_bytes(raw)
        try: pk.verify(signature, message); return True
        except InvalidSignature: return False
    except ImportError: pass
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
        try: VerifyKey(raw).verify(message, signature); return True
        except BadSignatureError: return False
    except ImportError: pass
    raise UpdateError("缺少签名验证库")

def verified_update_sha256(file_path, signature_bytes, public_key_b64=None):
    key = public_key_b64 or SIGNING_PUBLIC_KEY
    if not key: raise UpdateError("未配置公钥")
    if len(signature_bytes) != 64: raise UpdateError("签名长度错误")
    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): sha.update(chunk)
    digest = sha.digest()
    if _verify_ed25519(signature_bytes, digest, key): return sha.hexdigest()
    if _verify_ed25519(signature_bytes, sha.hexdigest().encode('ascii'), key): return sha.hexdigest()
    return None

def verify_update_signature(file_path, signature_bytes, public_key_b64=None):
    return verified_update_sha256(file_path, signature_bytes, public_key_b64) is not None

def verify_sha256(file_path, expected):
    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): sha.update(chunk)
    return sha.hexdigest().lower() == expected.lower()

def download_file(url, dest_path, progress_callback=None, cancel_event=None, **kwargs):
    if cancel_event is None: cancel_event = threading.Event()
    if urlparse(url).scheme != 'https': raise UpdateError("非 HTTPS")
    host = (urlparse(url).hostname or '').lower()
    if not _is_trusted_host(host): raise UpdateError("非受信域名")

    candidate_pairs = [(url, '直连')]
    for mirror in DOWNLOAD_MIRRORS:
        if not mirror: continue
        m_url = mirror.rstrip('/') + '/' + url
        candidate_pairs.append((m_url, mirror))

    for target_url, name in candidate_pairs:
        if cancel_event.is_set(): raise KeyboardInterrupt()
        # 每次切换源都重新计算已下载大小，避免沿用上一个源的状态
        existing = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        try:
            headers = {'Range': f'bytes={existing}-'} if existing > 0 else {}
            resp = _get_verified(_new_session(), target_url, stream=True, extra_headers=headers)
            if resp.status_code == 416:
                resp.close()
                if existing > 0: return dest_path  # 已完整
                else: continue
            if resp.status_code == 200:
                content_type = resp.headers.get('content-type', '').lower()
                if 'text/html' in content_type:
                    resp.close(); continue
                existing = 0; mode = 'wb'
            elif resp.status_code == 206:
                mode = 'ab'
            else:
                resp.close(); continue
            total = int(resp.headers.get('content-length', 0)) + (existing if mode == 'ab' else 0)
            downloaded = existing if mode == 'ab' else 0
            with open(dest_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if cancel_event.is_set(): raise KeyboardInterrupt()
                    if not chunk: continue
                    f.write(chunk); downloaded += len(chunk)
                    if progress_callback: progress_callback(downloaded, total, name, 0)
            resp.close()
            if total and downloaded != total: continue
            return dest_path
        except KeyboardInterrupt: raise
        except Exception: pass
    raise UpdateError("所有下载源失败")

def write_update_bat(exe_dir, temp_path, target_exe, expected_sha256=None):
    for p in (exe_dir, temp_path, target_exe):
        if any(c in p for c in '\r\n\x00"%!&|<>^'): raise UpdateError("路径含危险字符")
    if not expected_sha256 or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
        raise UpdateError("需提供 SHA-256")
    directory = exe_dir if os.access(exe_dir, os.W_OK) else os.path.dirname(temp_path)
    fd, bat_path = tempfile.mkstemp(prefix='SV_upd_', suffix='.bat', dir=directory)
    os.close(fd)
    lines = ["@echo off", "chcp 65001 > nul", "timeout /t 2 > nul"]
    lines.append(f"set EXPECTED={expected_sha256.upper()}")
    lines.append(f'for /f "skip=1 tokens=* delims=" %%H in (\'certutil -hashfile "{temp_path}" SHA256 ^| findstr /r /v "^CertUtil"\') do (')
    lines.append('    if not defined ACTUAL set "ACTUAL=%%H"')
    lines.append(')')
    lines.append('set "ACTUAL=%ACTUAL: =%"')
    lines.append('if /i not "%ACTUAL%"=="%EXPECTED%" goto fail')
    lines.append(f'copy /Y "{temp_path}" "{target_exe}"')
    lines.append('if errorlevel 1 goto fail')
    lines.append(f'del "{temp_path}"')
    lines.append('del "%~f0"')
    lines.append('exit /b 0')
    lines.append(':fail')
    lines.append(f'echo [ERROR] Failed to verify or replace: {temp_path}')
    lines.append('pause')
    lines.append('exit /b 1')
    with open(bat_path, 'w', encoding='utf-8') as f: f.write("\n".join(lines))
    return bat_path