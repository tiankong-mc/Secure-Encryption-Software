import os, re, time, hashlib
import requests
from packaging.version import parse as parse_version
from constants import VERSION

GITHUB_API = "https://api.github.com/repos/tiankong-mc/Secure-Encryption-Software/releases/latest"


class UpdateError(Exception):
    pass


def get_latest_release(timeout=15):
    """获取最新 release 信息，返回 dict。"""
    headers = {'User-Agent': 'SecureVault'}
    try:
        resp = requests.get(GITHUB_API, timeout=timeout, headers=headers, verify=False)
    except Exception as e:
        raise UpdateError(f"无法连接 GitHub: {e}")
    if resp.status_code != 200:
        raise UpdateError(f"HTTP {resp.status_code}")
    return resp.json()


def find_exe_asset(release_data):
    """从 release 中找出可执行文件附件。"""
    for a in release_data.get('assets', []):
        if a.get('name', '').lower() == 'encryption.exe':
            return a
    return None


def extract_sha256(release_data):
    """从 release 描述中提取 sha256（如有）。"""
    body = release_data.get('body', '') or ''
    m = re.search(r'sha256[:\s]*([a-fA-F0-9]{64})', body)
    return m.group(1).lower() if m else None


def download_file(url, dest_path, progress_callback=None,
                  max_retries=5, chunk_size=64 * 1024):
    """
    带断点续传 + 重试的下载。
    - progress_callback(downloaded, total) 用于更新进度条
    - 成功后返回 dest_path
    - 失败抛出 UpdateError
    """
    total = None
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            # 检查已下载部分
            existing = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

            headers = {'User-Agent': 'SecureVault'}
            if existing > 0:
                headers['Range'] = f'bytes={existing}-'

            resp = requests.get(url, stream=True, verify=False,
                                headers=headers, timeout=30)

            # 服务器支持断点续传：206 Partial Content
            if resp.status_code == 206:
                # Content-Range: bytes start-end/total
                cr = resp.headers.get('Content-Range', '')
                if '/' in cr:
                    total = int(cr.split('/')[-1])
                mode = 'ab'
                downloaded = existing
            elif resp.status_code == 200:
                # 不支持断点续传，从头开始
                total = int(resp.headers.get('content-length', 0)) or None
                mode = 'wb'
                downloaded = 0
            else:
                raise UpdateError(f"HTTP {resp.status_code}")

            with open(dest_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded, total)

            # 下载完成后检查大小
            final_size = os.path.getsize(dest_path)
            if total and final_size < total:
                raise UpdateError(f"下载不完整（{final_size}/{total} 字节）")

            return dest_path

        except Exception as e:
            last_err = e
            # 如果服务器不支持 Range，删掉残余文件，下次从头下载
            if isinstance(e, UpdateError) and "下载不完整" in str(e):
                pass  # 保留残余文件继续尝试断点续传
            time.sleep(min(2 ** attempt, 8))  # 指数退避：2, 4, 8, ...

    raise UpdateError(f"下载失败（已重试 {max_retries} 次）：{last_err}")


def verify_sha256(file_path, expected):
    """校验文件的 SHA-256。"""
    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest().lower() == expected.lower()


def is_newer(remote_tag):
    """远程版本是否比当前版本新。"""
    try:
        return parse_version(remote_tag) > parse_version(VERSION)
    except Exception:
        return False


def write_update_bat(exe_dir, temp_path, target_exe):
    """生成 update.bat 并返回路径。"""
    bat_path = os.path.join(exe_dir, "update.bat")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(f"""@echo off
timeout /t 2 > nul
copy /Y "{temp_path}" "{target_exe}"
del "{temp_path}"
del "%~f0"
""")
    return bat_path
