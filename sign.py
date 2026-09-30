"""对打包后的 exe 生成 Ed25519 签名。

使用方式：
    python sign.py

行为：
    - 若 signing.key 不存在，会先生成一对新密钥，并打印公钥让你填到 updater.py
    - 若 signing.key 已存在，直接用它对 dist/Encryption.exe 生成 .sig
    - 签名文件写到 dist/Encryption.exe.sig（64 字节原始二进制）

退出码：
    0  成功
    1  参数/环境错误
    2  签名失败
"""

import os
import sys
import base64
import hashlib

EXE_PATH = os.path.join('dist', 'Encryption.exe')
SIG_PATH = os.path.join('dist', 'Encryption.exe.sig')
KEY_PATH = 'signing.key'


def _check_cryptography():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        return True
    except ImportError:
        return False


def _raw_private_bytes(k):
    """兼容旧版 cryptography（< 41）。"""
    from cryptography.hazmat.primitives import serialization
    return k.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _raw_public_bytes(k):
    """兼容旧版 cryptography（< 41）。"""
    from cryptography.hazmat.primitives import serialization
    return k.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _ensure_key():
    """确保 signing.key 存在；不存在则生成并打印公钥。返回 True 表示本次新生成。"""
    if os.path.exists(KEY_PATH):
        return False

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    print()
    print('[首次] 未找到 signing.key，正在生成新密钥对...')
    k = Ed25519PrivateKey.generate()

    priv = _raw_private_bytes(k)
    pub = _raw_public_bytes(k)

    with open(KEY_PATH, 'wb') as f:
        f.write(priv)

    pub_b64 = base64.b64encode(pub).decode()

    print()
    print('=' * 64)
    print('  signing.key 已生成，请务必妥善保存！')
    print('  一旦丢失，将无法再为老用户发布后续更新。')
    print()
    print('  请把下面的公钥填入 updater.py 的 SIGNING_PUBLIC_KEY：')
    print()
    print(f'    SIGNING_PUBLIC_KEY = "{pub_b64}"')
    print()
    print('  填写完成后，请重新运行「封装.bat」打包一次，')
    print('  让新 exe 内置这份公钥，才能真正启用签名校验。')
    print('=' * 64)
    print()
    return True


def _sign():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.from_private_bytes(open(KEY_PATH, 'rb').read())
    with open(EXE_PATH, 'rb') as f:
        digest = hashlib.sha256(f.read()).digest()
    sig = k.sign(digest)

    with open(SIG_PATH, 'wb') as f:
        f.write(sig)

    return len(sig)


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
        newly_generated = _ensure_key()
        size = _sign()
    except Exception as e:
        print()
        print(f'[错误] 签名失败: {e}')
        print()
        return 2

    print(f'[信息] 签名已生成: {SIG_PATH} ({size} 字节)')
    if newly_generated:
        print()
        print('[!] 重要提醒：')
        print('    你刚生成了新的签名密钥，但 updater.py 里的 SIGNING_PUBLIC_KEY')
        print('    可能还是空的。请按上面的提示填入公钥后，重新打包一次。')
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
