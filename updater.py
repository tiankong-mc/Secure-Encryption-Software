import os, re, time, hashlib, tempfile, datetime, threading
from urllib.parse import urlparse, urlencode
import requests
from packaging.version import parse as parse_version
from constants import VERSION

UPDATER_REVISION = "2026-09-26-gitee-v10"

# ---------- 更新源配置 ----------
GITHUB_API = "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest"

# ---------- Gitee 配置 ----------
GITEE_OWNER = "tiankong_mc"
GITEE_REPO = "secure-vault"
# 有 token 就填，没有就留空字符串
# 公开仓库理论上不需要 token，但 Gitee 对匿名请求有限流，建议填上
GITEE_TOKEN = ""

# Gitee list 端点（latest 端点经常 404，改用列表取第一个）
# token 为空时，不拼 access_token 参数
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

# ---------- GitHub 镜像列表（Gitee 失败时使用） ----------
DOWNLOAD_MIRRORS = [
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghproxy.cc/",
    "https://ghp.ci/",
    "https://ghproxy.homeboyc.cn/",
    "",   # 直连 GitHub（保底）
]

# ---------- 下载策略参数 ----------
CHUNK_SIZE = 256 * 1024
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 30

SPEED_CHECK_WINDOW_SECONDS = 8.0
MIN_BYTES_RECEIVED_TO_ACCEPT = 50 * 1024

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


def _request_with_fallback(session, method, url, **kwargs):
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise UpdateError(f"拒绝非 HTTPS 请求: {url}")

    if 'timeout' not in kwargs:
        kwargs['timeout'] = (CONNECT_TIMEOUT, READ_TIMEOUT)

    try:
        return session.request(method, url, **kwargs)
    except requests.exceptions.SSLError as e1:
        if not _is_cert_error(e1):
            raise UpdateError(f"网络错误: {e1}") from e1
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e

    try:
        import certifi
        kwargs['verify'] = certifi.where()
        return session.request(method, url, **kwargs)
    except ImportError:
        pass
    except requests.exceptions.SSLError:
        pass
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e

    SSLTrustState.degraded = True
    SSLTrustState.degraded_reason = (
        "系统证书链不完整，已降级为跳过证书验证。\n"
        "建议安装 certifi（pip install certifi）以恢复完整验证。"
    )
    kwargs['verify'] = False
    try:
        return session.request(method, url, **kwargs)
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e


def _try_get(url, headers=None, timeout=15, stream=False, extra_headers=None):
    session = _new_session()
    if headers:
        session.headers.update(headers)
    if extra_headers:
        session.headers.update(extra_headers)
    return _request_with_fallback(session, 'GET', url,
                                  timeout=timeout, stream=stream)


# ============================================================
#  获取最新 Release
# ============================================================
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
    """从 Gitee 获取最新 Release（使用 list 端点，取第一个）。"""
    try:
        _debug_log(f"[{UPDATER_REVISION}] 请求 Gitee API (list): {GITEE_API}")
        resp = _try_get(GITEE_API, timeout=timeout)
        if resp.status_code != 200:
            _debug_log(f"[{UPDATER_REVISION}] Gitee 返回 HTTP {resp.status_code}: "
                       f"{resp.text[:200]}")
            return None
        data = resp.json()

        if isinstance(data, list):
            if not data:
                _debug_log(f"[{UPDATER_REVISION}] Gitee 没有任何 Release")
                return None
            first = data[0]
        elif isinstance(data, dict):
            first = data
        else:
            _debug_log(f"[{UPDATER_REVISION}] Gitee 返回了非预期类型: {type(data)}")
            return None

        normalized = _normalize_release(first, 'gitee')
        if normalized is None:
            return None
        tag = normalized.get('tag_name', '')
        _debug_log(f"[{UPDATER_REVISION}] Gitee 最新版本: {tag}, "
                   f"assets={len(normalized.get('assets', []) or [])}")
        return normalized
    except Exception as e:
        _debug_log(f"[{UPDATER_REVISION}] Gitee 请求失败: {e}")
        return None


def _fetch_github_release(timeout):
    try:
        _debug_log(f"[{UPDATER_REVISION}] 请求 GitHub API: {GITHUB_API}")
        resp = _try_get(GITHUB_API, timeout=timeout)
        if resp.status_code != 200:
            _debug_log(f"[{UPDATER_REVISION}] GitHub 返回 HTTP {resp.status_code}")
            return None
        data = resp.json()
        normalized = _normalize_release(data, 'github')
        if normalized is None:
            return None
        tag = normalized.get('tag_name', '')
        _debug_log(f"[{UPDATER_REVISION}] GitHub 最新版本: {tag}")
        return normalized
    except Exception as e:
        _debug_log(f"[{UPDATER_REVISION}] GitHub 请求失败: {e}")
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


def get_latest_release(timeout=15):
    """
    同时查询 Gitee 和 GitHub，返回版本号更高的 Release。
    优先使用 Gitee，但 Gitee 的 Release 必须有 exe 附件才算可用。
    """
    gitee_data = _fetch_gitee_release(timeout)
    github_data = _fetch_github_release(timeout)

    if gitee_data is not None and not _has_exe_asset(gitee_data):
        _debug_log(f"[{UPDATER_REVISION}] Gitee Release 没有 exe 附件，忽略")
        gitee_data = None

    if gitee_data is None and github_data is None:
        raise UpdateError("无法从 Gitee 或 GitHub 获取版本信息")

    if gitee_data is None:
        _debug_log(f"[{UPDATER_REVISION}] 仅 GitHub 可用")
        return github_data

    if github_data is None:
        _debug_log(f"[{UPDATER_REVISION}] 仅 Gitee 可用")
        return gitee_data

    gitee_tag = gitee_data.get('tag_name', '')
    github_tag = github_data.get('tag_name', '')

    if _tag_gt(github_tag, gitee_tag):
        _debug_log(f"[{UPDATER_REVISION}] GitHub 版本更新 "
                   f"({github_tag} > {gitee_tag})，使用 GitHub")
        return github_data
    else:
        _debug_log(f"[{UPDATER_REVISION}] 使用 Gitee 版本 ({gitee_tag})")
        return gitee_data


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


# ============================================================
#  单线程 + 断点续传下载
# ============================================================
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
        _debug_log(f"[{UPDATER_REVISION}] {source_name} 文件已完整（{existing} 字节）")
        if progress_callback:
            try:
                progress_callback(existing, existing, source_name, 0.0)
            except Exception:
                pass
        return True, None

    session = _new_session()
    headers = {}
    if existing > 0:
        headers['Range'] = f'bytes={existing}-'
        _debug_log(f"[{UPDATER_REVISION}] {source_name} 请求断点续传: 从 {existing} 开始")

    t_start = time.time()
    resp = _request_with_fallback(session, 'GET', url, stream=True, headers=headers)

    try:
        if resp.status_code == 206:
            cr = resp.headers.get('content-range', '')
            m = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', cr)
            if not m:
                _debug_log(f"[{UPDATER_REVISION}] {source_name} 206 响应缺少 Content-Range")
                return False, "206 响应格式异常"
            server_start = int(m.group(1))
            if server_start != existing:
                _debug_log(f"[{UPDATER_REVISION}] {source_name} 起点不符: "
                           f"期望 {existing}, 服务器 {server_start}")
                return False, "断点不一致"
            total = int(m.group(3))
            mode = 'ab'
            downloaded = existing
            bytes_at_source_start = existing
        elif resp.status_code == 200:
            if existing > 0:
                _debug_log(f"[{UPDATER_REVISION}] {source_name} 不支持续传"
                           f"（本地已有 {existing} 字节），跳过")
                return False, "服务器不支持续传"
            total = int(resp.headers.get('content-length', 0)) or None
            mode = 'wb'
            downloaded = 0
            bytes_at_source_start = 0
        elif resp.status_code == 416:
            if known_total and existing >= known_total:
                _debug_log(f"[{UPDATER_REVISION}] {source_name} 文件已达总大小")
                if progress_callback:
                    try:
                        progress_callback(existing, existing, source_name, 0.0)
                    except Exception:
                        pass
                return True, None
            _debug_log(f"[{UPDATER_REVISION}] {source_name} HTTP 416")
            return False, "HTTP 416"
        else:
            return False, f"HTTP {resp.status_code}"

        if known_total is None:
            known_total = total

        _debug_log(f"[{UPDATER_REVISION}] {source_name} 开始接收数据, "
                   f"总大小 {known_total}, 起始 {bytes_at_source_start}")

        last_report = 0.0
        last_log = 0.0
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
                        _debug_log(
                            f"[{UPDATER_REVISION}] {source_name} 8 秒内只收到 "
                            f"{bytes_from_this_source} 字节，切换下一个源 "
                            f"(已保留 {downloaded} 字节)")
                        return False, f"源 {source_name} 8 秒无有效数据"
                    else:
                        _debug_log(
                            f"[{UPDATER_REVISION}] {source_name} 通过检测，"
                            f"本次收到 {bytes_from_this_source} 字节，继续下载")

                if now - last_log >= 2.0:
                    last_log = now
                    _debug_log(f"[{UPDATER_REVISION}] {source_name} 进度 "
                               f"{downloaded}/{known_total} ({speed_kbps:.1f} KB/s)")

        if known_total and downloaded != known_total:
            _debug_log(f"[{UPDATER_REVISION}] {source_name} 下载大小不符: "
                       f"{downloaded}/{known_total}")
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


# ============================================================
#  下载入口
# ============================================================
def _download_from_gitee(url, dest_path, progress_callback, cancel_event):
    _debug_log(f"[{UPDATER_REVISION}] ===== Gitee 下载 {url} =====")
    ok, err = _download_one_source_resumable(
        url, dest_path, 'Gitee', None,
        progress_callback, cancel_event,
        speed_check_enabled=False)
    if ok:
        _debug_log(f"[{UPDATER_REVISION}] ===== Gitee 下载成功 =====")
        return dest_path
    raise UpdateError(f"Gitee 下载失败: {err}")


def _download_from_github(url, dest_path, progress_callback, cancel_event):
    _debug_log(f"[{UPDATER_REVISION}] ===== GitHub 下载 {url} =====")

    candidates = []
    for mirror in DOWNLOAD_MIRRORS:
        candidate = _apply_mirror(url, mirror)
        if candidate not in candidates:
            candidates.append(candidate)

    known_total = None
    last_err = None

    for idx, candidate_url in enumerate(candidates):
        if cancel_event.is_set():
            raise KeyboardInterrupt("__cancelled__")

        source_name = '直连GitHub' if not DOWNLOAD_MIRRORS[idx] \
                      else DOWNLOAD_MIRRORS[idx].rstrip('/')
        is_last = (idx == len(candidates) - 1)

        try:
            ok, err = _download_one_source_resumable(
                candidate_url, dest_path, source_name, known_total,
                progress_callback, cancel_event,
                speed_check_enabled=not is_last)
            if ok:
                _debug_log(f"[{UPDATER_REVISION}] ===== 下载成功 (源: {source_name}) =====")
                return dest_path
            last_err = err
            _debug_log(f"[{UPDATER_REVISION}] {source_name} 失败: {err}，换下一个源")
        except KeyboardInterrupt:
            raise
        except UpdateError as e:
            last_err = str(e)
            _debug_log(f"[{UPDATER_REVISION}] {source_name} 异常: {last_err}")
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            _debug_log(f"[{UPDATER_REVISION}] {source_name} 异常: {last_err}")

    _debug_log(f"[{UPDATER_REVISION}] ===== 所有 GitHub 源均失败 =====")
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


def write_update_bat(exe_dir, temp_path, target_exe):
    bat_path = os.path.join(exe_dir, "update.bat")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(f"""@echo off
timeout /t 2 > nul
copy /Y "{temp_path}" "{target_exe}"
if errorlevel 1 goto failed
del "{temp_path}"
del "%~f0"
exit /b 0
:failed
echo SecureVault update failed. The downloaded file is kept at:
echo "{temp_path}"
pause
""")
    return bat_path
