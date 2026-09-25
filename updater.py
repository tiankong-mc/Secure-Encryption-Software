import os, re, time, hashlib
from urllib.parse import urlparse
import requests
from packaging.version import parse as parse_version
from constants import VERSION

GITHUB_API = "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest"

TRUSTED_HOSTS = ('github.com',)
TRUSTED_SUFFIXES = ('.github.com', '.githubusercontent.com')


class UpdateError(Exception):
    pass


class SSLTrustState:
    """记录本次会话中 SSL 是否被降级，UI 层可读取以显示警告。"""
    degraded = False
    degraded_reason = None


def _is_trusted_host(host):
    host = (host or '').lower()
    return host in TRUSTED_HOSTS or any(host.endswith(s) for s in TRUSTED_SUFFIXES)


def _is_cert_error(exc):
    msg = str(exc).lower()
    return ('certificate verify failed' in msg
            or 'sslcertverificationerror' in msg
            or 'certificate_verify_failed' in msg)


def _try_get(url, headers=None, timeout=15, stream=False, extra_headers=None):
    """
    分级 HTTPS GET：
    1. 系统默认验证
    2. certifi 证书
    3. verify=False 兜底（记录警告）
    """
    final_headers = dict(headers or {})
    if extra_headers:
        final_headers.update(extra_headers)

    # 第一级
    try:
        return requests.get(url, headers=final_headers, timeout=timeout, stream=stream)
    except requests.exceptions.SSLError as e1:
        if not _is_cert_error(e1):
            raise UpdateError(f"网络错误: {e1}") from e1
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e

    # 第二级：certifi
    try:
        import certifi
        return requests.get(url, headers=final_headers, timeout=timeout,
                            stream=stream, verify=certifi.where())
    except ImportError:
        pass
    except requests.exceptions.SSLError:
        pass
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e

    # 第三级：降级
    SSLTrustState.degraded = True
    SSLTrustState.degraded_reason = (
        "系统证书链不完整，已降级为跳过证书验证。\n"
        "建议安装 certifi（pip install certifi）以恢复完整验证。"
    )
    try:
        return requests.get(url, headers=final_headers, timeout=timeout,
                            stream=stream, verify=False)
    except requests.exceptions.RequestException as e:
        raise UpdateError(f"网络错误: {e}") from e


def get_latest_release(timeout=15):
    headers = {'User-Agent': 'SecureVault'}
    resp = _try_get(GITHUB_API, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise UpdateError(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as e:
        raise UpdateError("GitHub 返回了无效数据") from e
    if not isinstance(data, dict):
        raise UpdateError("GitHub 返回的数据格式无效")
    return data


def find_exe_asset(release_data):
    for a in release_data.get('assets', []):
        if a.get('name', '').lower() in ('encryption.exe', 'securevault.exe'):
            return a
    return None


def extract_sha256(release_data):
    """
    从 Release body 中提取 SHA-256。
    兼容以下写法（大小写不敏感，连字符 / 空格可选）：
      - SHA-256: <64 位 hex>
      - SHA256: <64 位 hex>
      - sha-256 <64 位 hex>
      - sha256:<64 位 hex>
      - sha 256 <64 位 hex>
    返回小写的 64 位十六进制字符串，若未找到则返回 None。
    """
    body = release_data.get('body', '') or ''
    # sha[- ]?256  匹配 sha256 / sha-256 / sha 256
    # [:\s]*       允许冒号 / 空白分隔
    # [a-fA-F0-9]{64}  正好 64 位十六进制
    # re.IGNORECASE  大小写不敏感
    m = re.search(r'sha[- ]?256[:\s]*([a-fA-F0-9]{64})', body, re.IGNORECASE)
    return m.group(1).lower() if m else None


def download_file(url, dest_path, progress_callback=None,
                  max_retries=5, chunk_size=64 * 1024):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not _is_trusted_host(parsed.hostname):
        raise UpdateError("拒绝从非 GitHub HTTPS 地址下载更新")

    last_err = None
    expected_total = None

    for attempt in range(1, max_retries + 1):
        resp = None
        try:
            existing = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

            extra = {}
            if existing > 0:
                extra['Range'] = f'bytes={existing}-'

            resp = _try_get(url, headers={'User-Agent': 'SecureVault'},
                            timeout=30, stream=True, extra_headers=extra)

            final = urlparse(getattr(resp, 'url', url))
            if final.scheme != 'https' or not _is_trusted_host(final.hostname):
                raise UpdateError("GitHub 将下载重定向到了不受信任的地址")

            if resp.status_code == 206:
                cr = resp.headers.get('Content-Range', '')
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', cr)
                if not match or int(match.group(1)) != existing:
                    with open(dest_path, 'wb'):
                        pass
                    raise UpdateError("服务器返回了无效的断点续传范围")
                expected_total = int(match.group(3))
                mode = 'ab'
                downloaded = existing
            elif resp.status_code == 200:
                expected_total = int(resp.headers.get('content-length', 0)) or None
                mode = 'wb'
                downloaded = 0
            elif resp.status_code == 416 and existing:
                match = re.fullmatch(r'bytes \*/(\d+)', resp.headers.get('Content-Range', ''))
                if match and existing == int(match.group(1)):
                    return dest_path
                with open(dest_path, 'wb'):
                    pass
                raise UpdateError("本地断点与服务器文件不一致")
            else:
                raise UpdateError(f"HTTP {resp.status_code}")

            with open(dest_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and expected_total:
                        progress_callback(downloaded, expected_total)

            final_size = os.path.getsize(dest_path)
            if expected_total and final_size != expected_total:
                raise UpdateError(f"下载大小不正确（{final_size}/{expected_total} 字节）")

            return dest_path

        except UpdateError:
            raise
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 8))
        finally:
            if resp is not None:
                close = getattr(resp, 'close', None)
                if close:
                    close()

    raise UpdateError(f"下载失败（已重试 {max_retries} 次）：{last_err}")


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
