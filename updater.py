import os, re, time, hashlib, tempfile, datetime, threading, base64
from urllib.parse import urlparse, urlencode, urljoin
import requests
from packaging.version import parse as parse_version
from constants import VERSION

UPDATER_REVISION = "2026-09-30-signed-v14"

GITHUB_API = "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest"

GITEE_OWNER = "tiankong_mc"
GITEE_REPO = "secure-vault"
GITEE_TOKEN = ""

_gitee_params = {
    'direction': 'desc',
    'per_page': '5',
}
if GITEE_TOKEN:
    _gitee_params['access_token'] = GITEE_TOKEN
GITEE_API = (
    f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}"
    f"/releases?{urlencode(_gitee_params)}"
)

# Ed25519 发布者公钥（base64 的 32 字节原始公钥）。留空则跳过签名校验。
SIGNING_PUBLIC_KEY = "nx697jofj6nw3UZhnJpKixo2E+lbf90pcpisC2v2GRw="

DOWNLOAD_MIRRORS = [
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghproxy.cc/",
    "https://ghp.ci/",
    "https://ghproxy.homeboyc.cn/",
    "",
]

CHUNK_SIZE = 256 * 1024
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30

SPEED_CHECK_WINDOW_SECONDS = 8.0
MIN_BYTES_RECEIVED_TO_ACCEPT = 50 * 1024

MAX_VERIFY_RESPONSE_SIZE = 4096
MAX_SIGNATURE_SIZE = 1024
MAX_REDIRECTS = 5

TRUSTED_HOSTS = ('github.com',)
TRUSTED_SUFFIXES = ('.github.com', '.githubusercontent.com')
TRUSTED_GITEE_HOSTS = ('gitee.com',)
TRUSTED_GITEE_SUFFIXES = ('.gitee.com',)


def _debug_log(message):
    try:
        log_path = os.path.join(tempfile.gettempdir(), 'SecureVault_updater.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{ts} - {message}\n")
    except Exception:
        pass


class UpdateError(Exception):
    pass


class SSLTrustState:
    degraded = False
    degraded_reason = None


def _is_trusted_host(host):
    host = (host or '').lower()
    return host in TRUSTED_HOSTS or any(host.endswith(s) for s in TRUSTED_SUFFIXES)


def _is_gitee_host(host):
    host = (host or '').lower()
    return host in TRUSTED_GITEE_HOSTS or any(host.endswith(s) for s in TRUSTED_GITEE_SUFFIXES)


def _is_any_trusted_host(host):
    return _is_trusted_host(host) or _is_gitee_host(host)


def _is_cert_error(exc):
    msg = str(exc).lower()
    return ('certificate verify failed' in msg
            or 'sslcertverificationerror' in msg
            or 'certificate_verify_failed' in msg)


def _parse_tag_safe(tag):
    try:
        return parse_version(tag)
    except Exception:
        return None


def _tag_gt(a, b):
    pa = _parse_tag_safe(a)
    pb = _parse_tag_safe(b)
    if pa is None or pb is None:
        return False
    return pa > pb


def _new_session():
    s = requests.Session()
    s.headers.update({'User-Agent': 'SecureVault'})
    return s


def _request_strict(session, method, url, **kwargs):
    """严格 HTTPS 请求：系统 → certifi，绝不降级到 verify=False。"""
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise UpdateError(f"拒绝非 HTTPS 请求: {url}")

    if 'timeout' not in kwargs:
        kwargs['timeout'] = (CONNECT_TIMEOUT, READ_TIMEOUT)

    first_err = None
    try:
        return session.request(method, url, **kwargs)
    except requests.exceptions.SSLError as e1:
        first_err = e1
        if not _is_cert_error(e1):
            raise UpdateError(f"网络错误: {e1}") from e1
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e

    try:
        import certifi
        kwargs['verify'] = certifi.where()
        return session.request(method, url, **kwargs)
    except ImportError:
        raise UpdateError(
            "TLS 证书校验失败，且未安装 certifi 库。\n"
            "出于安全考虑，不降级为跳过证书验证。\n"
            "建议安装 certifi（pip install certifi）后重试。"
        ) from first_err
    except requests.exceptions.SSLError as e2:
        raise UpdateError(
            f"TLS 证书校验失败（系统信任链与 certifi 均失败）：{e2}\n"
            "可能的原因：网络被中间人劫持、系统时间不正确或证书过期。\n"
            "出于安全考虑，拒绝继续。"
        ) from e2
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e


def _get_verified(session, url, *, stream=False, timeout=None, extra_headers=None,
                  max_redirects=MAX_REDIRECTS):
    """逐跳校验重定向主机名。"""
    final_headers = dict(extra_headers or {})
    current = url

    for _ in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme != 'https':
            raise UpdateError(f"重定向到非 HTTPS 地址: {current}")
        host = (parsed.hostname or '').lower()
        if not _is_any_trusted_host(host):
            raise UpdateError(f"重定向到非受信域名: {host}")

        kwargs = {'stream': stream, 'allow_redirects': False}
        if timeout is not None:
            kwargs['timeout'] = timeout
        if final_headers:
            kwargs['headers'] = final_headers

        resp = _request_strict(session, 'GET', current, **kwargs)

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('Location')
            if not location:
                return resp
            try:
                resp.close()
            except Exception:
                pass
            current = urljoin(current, location)
            continue
        return resp

    raise UpdateError("重定向次数过多")


def _try_get(url, headers=None, timeout=15, stream=False, extra_headers=None):
    session = _new_session()
    if headers:
        session.headers.update(headers)
    return _get_verified(session, url, stream=stream, timeout=timeout,
                         extra_headers=extra_headers)


def _read_response_capped(resp, cap=MAX_VERIFY_RESPONSE_SIZE):
    chunks = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=4096):
            if not chunk:
                continue
            total += len(chunk)
            if total > cap:
                chunks.append(chunk[:cap - (total - len(chunk))])
                return b''.join(chunks), True
            chunks.append(chunk)
    except Exception as e:
        raise UpdateError(f"读取响应失败: {e}") from e
    return b''.join(chunks), False


def get_latest_release(timeout=15):
    gitee_data = _fetch_gitee_release(timeout)
    github_data = _fetch_github_release(timeout)

    if gitee_data is not None and not _has_exe_asset(gitee_data):
        _debug_log(f"[{UPDATER_REVISION}] Gitee Release 没有 exe 附件，忽略")
        gitee_data = None

    if gitee_data is None and github_data is None:
        raise UpdateError("无法从 Gitee 或 GitHub 获取版本信息")

    if gitee_data is None:
        return github_data
    if github_data is None:
        return gitee_data

    gitee_tag = gitee_data.get('tag_name', '')
    github_tag = github_data.get('tag_name', '')

    if _tag_gt(github_tag, gitee_tag):
        _debug_log(f"[{UPDATER_REVISION}] 使用 GitHub ({github_tag})")
        return github_data
    else:
        _debug_log(f"[{UPDATER_REVISION}] 使用 Gitee ({gitee_tag})")
        return gitee_data


def _normalize_release(data, source):
    if not isinstance(data, dict):
        return None
    normalized = dict(data)
    body = normalized.get('body')
    if not body:
        body = data.get('description', '') or ''
        normalized['body'] = body
    normalized['_source'] = source
    return normalized


def _fetch_gitee_release(timeout):
    try:
        _debug_log(f"[{UPDATER_REVISION}] 请求 Gitee API")
        resp = _try_get(GITEE_API, timeout=timeout)
        if resp.status_code != 200:
            _debug_log(f"[{UPDATER_REVISION}] Gitee HTTP {resp.status_code}")
            return None
        data = resp.json()
        if isinstance(data, list):
            if not data:
                return None
            first = data[0]
        elif isinstance(data, dict):
            first = data
        else:
            return None
        normalized = _normalize_release(first, 'gitee')
        if normalized is None:
            return None
        tag = normalized.get('tag_name', '')
        _debug_log(f"[{UPDATER_REVISION}] Gitee 最新: {tag}")
        return normalized
    except Exception as e:
        _debug_log(f"[{UPDATER_REVISION}] Gitee 失败: {e}")
        return None


def _fetch_github_release(timeout):
    try:
        _debug_log(f"[{UPDATER_REVISION}] 请求 GitHub API")
        resp = _try_get(GITHUB_API, timeout=timeout)
        if resp.status_code != 200:
            _debug_log(f"[{UPDATER_REVISION}] GitHub HTTP {resp.status_code}")
            return None
        data = resp.json()
        normalized = _normalize_release(data, 'github')
        if normalized is None:
            return None
        tag = normalized.get('tag_name', '')
        _debug_log(f"[{UPDATER_REVISION}] GitHub 最新: {tag}")
        return normalized
    except Exception as e:
        _debug_log(f"[{UPDATER_REVISION}] GitHub 失败: {e}")
        return None


def _has_exe_asset(release_data):
    if not isinstance(release_data, dict):
        return False
    for a in release_data.get('assets', []) or []:
        if not isinstance(a, dict):
            continue
        name = (a.get('name') or a.get('title') or '').lower()
        url = a.get('browser_download_url', '') or ''
        if name in ('encryption.exe', 'securevault.exe') and url:
            return True
    return False


def find_exe_asset(release_data):
    if not isinstance(release_data, dict):
        return None
    source = release_data.get('_source', 'github')
    assets = release_data.get('assets', []) or []
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = (a.get('name') or a.get('title') or '').lower()
        if name in ('encryption.exe', 'securevault.exe'):
            url = a.get('browser_download_url', '') or ''
            if not url:
                continue
            return {
                'browser_download_url': url,
                'name': a.get('name') or a.get('title') or 'Encryption.exe',
                '_source': source,
            }
    return None


def find_signature_asset(release_data):
    """
    修复 A3：精确匹配与 exe 同名的 .sig 附件（如 Encryption.exe.sig），
    避免误匹配其他以 .sig 结尾的文件。
    """
    if not isinstance(release_data, dict):
        return None

    exe_asset = find_exe_asset(release_data)
    if not exe_asset:
        return None

    exe_name = (exe_asset.get('name') or '').lower()
    if not exe_name:
        return None
    wanted = exe_name + '.sig'

    source = release_data.get('_source', 'github')
    assets = release_data.get('assets', []) or []
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = (a.get('name') or a.get('title') or '').lower()
        if name == wanted:
            url = a.get('browser_download_url', '') or ''
            if not url:
                continue
            return {
                'browser_download_url': url,
                'name': a.get('name') or a.get('title') or wanted,
                '_source': source,
            }
    return None


def extract_sha256(release_data):
    if not isinstance(release_data, dict):
        return None
    body = release_data.get('body', '') or ''
    text = re.sub(r'[*_`~\\]', '', body)
    m = re.search(r'sha[\s\-]*256[\s\S]{0,200}?([a-fA-F0-9]{64})',
                  text, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    hashes = re.findall(r'\b([a-fA-F0-9]{64})\b', text)
    if hashes:
        return hashes[0].lower()
    return None


def _apply_mirror(url, mirror_prefix):
    if not mirror_prefix:
        return url
    if not url.startswith('https://github.com/'):
        return url
    return mirror_prefix.rstrip('/') + '/' + url


def download_signature(url, timeout=15):
    session = _new_session()
    resp = _get_verified(session, url, stream=True, timeout=timeout)
    try:
        if resp.status_code != 200:
            raise UpdateError(f"下载签名失败: HTTP {resp.status_code}")
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=512):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_SIGNATURE_SIZE:
                raise UpdateError("签名文件异常大")
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _load_ed25519_public_key(public_key_b64):
    try:
        raw = base64.b64decode(public_key_b64.strip(), validate=True)
    except Exception as e:
        raise UpdateError(f"公钥不是有效的 base64: {e}") from e
    if len(raw) != 32:
        raise UpdateError(f"Ed25519 公钥长度应为 32 字节，实际 {len(raw)} 字节")
    return raw


def _verify_ed25519(signature, message, public_key_b64):
    if len(signature) != 64:
        raise UpdateError(f"Ed25519 签名应为 64 字节，实际 {len(signature)} 字节")

    pubkey_raw = _load_ed25519_public_key(public_key_b64)

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pk = Ed25519PublicKey.from_public_bytes(pubkey_raw)
        try:
            pk.verify(signature, message)
            return True
        except InvalidSignature:
            return False
    except ImportError:
        pass

    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
        vk = VerifyKey(pubkey_raw)
        try:
            vk.verify(message, signature)
            return True
        except BadSignatureError:
            return False
    except ImportError:
        pass

    raise UpdateError(
        "已配置签名公钥，但未安装 Ed25519 校验库。\n"
        "出于安全考虑，拒绝在无签名校验能力的情况下更新。\n"
        "请安装 cryptography（推荐，pip install cryptography）或 PyNaCl（pip install pynacl）。")


def verify_update_signature(file_path, signature_bytes, public_key_b64=None):
    key = public_key_b64 if public_key_b64 is not None else SIGNING_PUBLIC_KEY
    if not key:
        raise UpdateError("未配置签名公钥，无法进行签名校验")

    sig = _decode_signature_blob(signature_bytes)

    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(chunk)
    digest = sha.digest()

    if _verify_ed25519(sig, digest, key):
        return True
    try:
        if _verify_ed25519(sig, sha.hexdigest().encode('ascii'), key):
            return True
    except UpdateError:
        raise

    return False


def _decode_signature_blob(blob):
    if not isinstance(blob, (bytes, bytearray)):
        blob = bytes(blob)
    if len(blob) == 64:
        return bytes(blob)

    try:
        cleaned = bytes(blob).strip()
        decoded = base64.b64decode(cleaned, validate=True)
        if len(decoded) == 64:
            return decoded
    except Exception:
        pass

    try:
        text = bytes(blob).strip().decode('ascii', errors='ignore')
        decoded = bytes.fromhex(text)
        if len(decoded) == 64:
            return decoded
    except Exception:
        pass

    if len(blob) >= 69 and blob[:4] == b'SVSG' and blob[4] == 1:
        return bytes(blob[5:69])

    raise UpdateError(f"无法解析签名文件（长度 {len(blob)} 字节）")


def _get_local_size(dest_path):
    try:
        if os.path.exists(dest_path):
            return os.path.getsize(dest_path)
    except OSError:
        pass
    return 0


def _download_one_source_resumable(url, dest_path, source_name, known_total,
                                    progress_callback, cancel_event,
                                    speed_check_enabled=True):
    existing = _get_local_size(dest_path)

    if known_total is not None and existing == known_total and existing > 0:
        if progress_callback:
            try:
                progress_callback(existing, existing, source_name, 0.0)
            except Exception:
                pass
        return True, None

    session = _new_session()
    extra_headers = {}
    if existing > 0:
        extra_headers['Range'] = f'bytes={existing}-'

    t_start = time.time()
    resp = _get_verified(session, url, stream=True, extra_headers=extra_headers)

    try:
        if resp.status_code == 206:
            cr = resp.headers.get('content-range', '')
            m = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', cr)
            if not m:
                return False, "206 响应格式异常"
            server_start = int(m.group(1))
            if server_start != existing:
                return False, "断点不一致"
            total = int(m.group(3))
            mode = 'ab'
            downloaded = existing
            bytes_at_source_start = existing
        elif resp.status_code == 200:
            if existing > 0:
                return False, "服务器不支持续传"
            total = int(resp.headers.get('content-length', 0)) or None
            mode = 'wb'
            downloaded = 0
            bytes_at_source_start = 0
        elif resp.status_code == 416:
            if known_total and existing >= known_total:
                if progress_callback:
                    try:
                        progress_callback(existing, existing, source_name, 0.0)
                    except Exception:
                        pass
                return True, None
            return False, "HTTP 416"
        else:
            return False, f"HTTP {resp.status_code}"

        if known_total is None:
            known_total = total

        last_report = 0.0
        speed_checked = False

        with open(dest_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if cancel_event.is_set():
                    raise KeyboardInterrupt("__cancelled__")
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                elapsed = now - t_start
                bytes_from_this_source = downloaded - bytes_at_source_start
                speed_kbps = bytes_from_this_source / max(elapsed, 0.001) / 1024.0

                if progress_callback and now - last_report >= 0.3:
                    last_report = now
                    try:
                        progress_callback(downloaded, known_total,
                                          source_name, speed_kbps)
                    except Exception:
                        pass

                if (speed_check_enabled and not speed_checked
                        and elapsed >= SPEED_CHECK_WINDOW_SECONDS):
                    speed_checked = True
                    if bytes_from_this_source < MIN_BYTES_RECEIVED_TO_ACCEPT:
                        return False, f"源 {source_name} 8 秒无有效数据"

        if known_total and downloaded != known_total:
            return False, f"下载大小不正确（{downloaded}/{known_total}）"

        if progress_callback:
            elapsed = max(time.time() - t_start, 0.001)
            speed = (downloaded - bytes_at_source_start) / elapsed / 1024.0
            try:
                progress_callback(downloaded, downloaded, source_name, speed)
            except Exception:
                pass

        return True, None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _download_from_gitee(url, dest_path, progress_callback, cancel_event):
    ok, err = _download_one_source_resumable(
        url, dest_path, 'Gitee', None,
        progress_callback, cancel_event,
        speed_check_enabled=False)
    if ok:
        return dest_path
    raise UpdateError(f"Gitee 下载失败: {err}")


def _download_from_github(url, dest_path, progress_callback, cancel_event):
    candidate_pairs = []
    seen = set()
    for mirror in DOWNLOAD_MIRRORS:
        candidate = _apply_mirror(url, mirror)
        if candidate in seen:
            continue
        seen.add(candidate)
        name = '直连GitHub' if not mirror else mirror.rstrip('/')
        candidate_pairs.append((candidate, name))

    known_total = None
    last_err = None

    for idx, (candidate_url, source_name) in enumerate(candidate_pairs):
        if cancel_event.is_set():
            raise KeyboardInterrupt("__cancelled__")

        is_last = (idx == len(candidate_pairs) - 1)

        try:
            ok, err = _download_one_source_resumable(
                candidate_url, dest_path, source_name, known_total,
                progress_callback, cancel_event,
                speed_check_enabled=not is_last)
            if ok:
                return dest_path
            last_err = err
        except KeyboardInterrupt:
            raise
        except UpdateError as e:
            last_err = str(e)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"

    raise UpdateError(f"所有下载源均失败，最后错误：{last_err}")


def download_file(url, dest_path, progress_callback=None,
                  max_retries=3, chunk_size=None, cancel_event=None):
    if cancel_event is None:
        cancel_event = threading.Event()

    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise UpdateError(f"拒绝非 HTTPS 请求: {url}")

    host = (parsed.hostname or '').lower()

    if _is_gitee_host(host):
        return _download_from_gitee(url, dest_path, progress_callback, cancel_event)

    if not _is_trusted_host(host):
        raise UpdateError(f"拒绝从非 GitHub / Gitee HTTPS 地址下载更新: {host}")

    return _download_from_github(url, dest_path, progress_callback, cancel_event)


def verify_sha256(file_path, expected):
    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest().lower() == expected.lower()


def is_newer(remote_tag):
    try:
        return parse_version(remote_tag) > parse_version(VERSION)
    except Exception:
        return False


def _is_dir_writable(directory):
    test_path = os.path.join(directory, f'.sv_write_test_{os.getpid()}')
    try:
        with open(test_path, 'wb') as f:
            f.write(b'test')
        os.remove(test_path)
        return True
    except OSError:
        return False


def write_update_bat(exe_dir, temp_path, target_exe, expected_sha256=None):
    bat_path = None
    if _is_dir_writable(exe_dir):
        bat_path = os.path.join(exe_dir, "SecureVault_update.bat")
    else:
        temp_dir = tempfile.gettempdir()
        bat_path = os.path.join(temp_dir, f"SecureVault_update_{os.getpid()}.bat")

    lines = []
    lines.append("@echo off")
    lines.append("setlocal enabledelayedexpansion")
    lines.append("timeout /t 2 > nul")
    lines.append("")

    if expected_sha256:
        lines.append("set EXPECTED_SHA=" + expected_sha256.upper())
        lines.append("set ACTUAL_SHA=")
        lines.append('for /f "skip=1 tokens=* delims=" %%H in (\'certutil -hashfile "'
                     + temp_path + '" SHA256 ^| findstr /r /v "^CertUtil"\') do (')
        lines.append("    if not defined ACTUAL_SHA set \"ACTUAL_SHA=%%H\"")
        lines.append(")")
        lines.append("set \"ACTUAL_SHA=!ACTUAL_SHA: =!\"")
        lines.append("if /i not \"!ACTUAL_SHA!\"==\"!EXPECTED_SHA!\" goto hashfail")
        lines.append("")

    lines.append('copy /Y "' + temp_path + '" "' + target_exe + '"')
    lines.append("if errorlevel 1 goto failed")
    lines.append('del "' + temp_path + '"')
    lines.append('del "%~f0"')
    lines.append("exit /b 0")
    lines.append("")
    lines.append(":hashfail")
    lines.append("echo.")
    lines.append("echo [ERROR] SHA-256 mismatch. The downloaded file is kept at:")
    lines.append('echo   "' + temp_path + '"')
    lines.append("pause")
    lines.append("exit /b 1")
    lines.append("")
    lines.append(":failed")
    lines.append("echo.")
    lines.append("echo [ERROR] Failed to replace the executable.")
    lines.append("echo The downloaded file is kept at:")
    lines.append('echo   "' + temp_path + '"')
    lines.append("echo.")
    lines.append("echo Try running this script as Administrator:")
    lines.append('echo   "' + bat_path + '"')
    lines.append("pause")
    lines.append("exit /b 1")
    lines.append("")

    try:
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
    except OSError as e:
        raise UpdateError(f"无法写入更新脚本 {bat_path}: {e}") from e

    return bat_path
