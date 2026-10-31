"""对打包后的 exe 生成 Ed25519 签名。

使用方式：
    python sign.py

密钥查找顺序：
    1. 环境变量 SECUREVAULT_SIGNING_KEY 指向的路径
    2. %USERPROFILE%\\.securevault\\signing.key（推荐，避免私钥进源码仓库）
    3. 当前目录的 signing.key（兼容旧习惯）

行为：
    - 找不到私钥时生成到 %USERPROFILE%\\.securevault\\signing.key，并打印公钥，
      此时不会继续签名（必须先更新 updater.py 的 SIGNING_PUBLIC_KEY 并重新打包）。
    - 签名前会校验私钥推导出的公钥与 updater.SIGNING_PUBLIC_KEY 一致，
      不一致直接报错，避免发布出用户端永远验签失败的版本。
    - 签名后本地再验签一次，只有验签通过才返回 0。
    - 签名文件写到 dist/Encryption.exe.sig（64 字节原始二进制）。

退出码：
    0  成功
    1  参数/环境错误
    2  签名/密钥不匹配
    3  签名后自检失败
"""

import os
import sys
import base64
import hashlib
import hmac

EXE_PATH = os.path.join('dist', 'Encryption.exe')
SIG_PATH = os.path.join('dist', 'Encryption.exe.sig')
LOCAL_KEY_PATH = 'signing.key'
ENV_KEY = 'SECUREVAULT_SIGNING_KEY'
HOME_KEY_PATH = os.path.join(os.path.expanduser('~'), '.securevault', 'signing.key')


def _check_cryptography():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        return True
    except ImportError:
        return False


def _raw_public_bytes(k):
    from cryptography.hazmat.primitives import serialization
    return k.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _key_candidates():
    paths = []
    env = os.environ.get(ENV_KEY)
    if env:
        paths.append(os.path.abspath(env))
    paths.append(HOME_KEY_PATH)
    paths.append(os.path.abspath(LOCAL_KEY_PATH))
    return paths


def _find_key():
    for path in _key_candidates():
        if os.path.exists(path):
            return path
    return None


def _ensure_key():
    """返回 (key_path, newly_generated)。找不到时生成到用户目录。"""
    found = _find_key()
    if found:
        return found, False

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    os.makedirs(os.path.dirname(HOME_KEY_PATH), exist_ok=True)
    with open(HOME_KEY_PATH, 'wb') as f:
        f.write(priv)
    try:
        os.chmod(HOME_KEY_PATH, 0o600)
    except Exception:
        pass

    pub_b64 = base64.b64encode(_raw_public_bytes(key)).decode()
    print()
    print('=' * 64)
    print('  已生成新的签名私钥：')
    print(f'    {HOME_KEY_PATH}')
    print('  请务必离线备份！一旦丢失，将无法再为老用户发布后续更新。')
    print()
    print('  请把下面的公钥填入 updater.py 的 SIGNING_PUBLIC_KEY：')
    print()
    print(f'    SIGNING_PUBLIC_KEY = "{pub_b64}"')
    print()
    print('  填写后重新运行「封装.bat」打包，让新 exe 内置这份公钥。')
    print('=' * 64)
    print()
    return HOME_KEY_PATH, True


def _load_private_key(path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    with open(path, 'rb') as f:
        return Ed25519PrivateKey.from_private_bytes(f.read())


def _sign(key_path):
    key = _load_private_key(key_path)
    with open(EXE_PATH, 'rb') as f:
        digest = hashlib.sha256(f.read()).digest()
    sig = key.sign(digest)
    with open(SIG_PATH, 'wb') as f:
        f.write(sig)
    return len(sig)


def _check_key_matches_embedded(key_path):
    """私钥推导出的公钥必须与 exe 内置的 updater.SIGNING_PUBLIC_KEY 一致。"""
    import updater
    key = _load_private_key(key_path)
    derived_b64 = base64.b64encode(_raw_public_bytes(key)).decode()
    embedded = (updater.SIGNING_PUBLIC_KEY or '').strip()
    if not embedded:
        print('[错误] updater.SIGNING_PUBLIC_KEY 为空，用户端会拒绝自动更新。')
        print(f'       请先填入公钥：SIGNING_PUBLIC_KEY = "{derived_b64}"')
        return False
    if not hmac.compare_digest(derived_b64, embedded):
        print('[错误] 签名私钥与 updater.SIGNING_PUBLIC_KEY 不匹配！')
        print(f'       私钥推导公钥: {derived_b64}')
        print(f'       程序内置公钥: {embedded}')
        print('       这样签名出的 .sig 用户端 100% 验签失败，已中止。')
        return False
    return True


def main():
    if not _check_cryptography():
        print()
        print('[错误] 未安装 cryptography 库，无法生成签名。')
        print('       请运行: pip install cryptography')
        print()
        return 1

    if not os.path.exists(EXE_PATH):
        print()
        print(f'[错误] 找不到 {EXE_PATH}')
        print('       请先运行「封装.bat」完成打包。')
        print()
        return 1

    try:
        key_path, newly_generated = _ensure_key()
    except Exception as e:
        print()
        print(f'[错误] 读取/生成密钥失败: {e}')
        print()
        return 2

    if newly_generated:
        return 1

    try:
        if not _check_key_matches_embedded(key_path):
            return 2
        size = _sign(key_path)
    except Exception as e:
        print()
        print(f'[错误] 签名失败: {e}')
        print()
        return 2

    try:
        import updater
        with open(SIG_PATH, 'rb') as f:
            sig = f.read()
        if not updater.verify_update_signature(EXE_PATH, sig):
            print('[错误] 签名后自检失败：生成的 .sig 无法通过内置公钥验证。')
            return 3
    except Exception as e:
        print(f'[错误] 签名后自检异常: {e}')
        return 3

    print(f'[信息] 签名已生成并通过自检: {SIG_PATH} ({size} 字节)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
