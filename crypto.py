from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import os

def encrypt_data(data: bytes, key: bytes) -> bytes:
    """使用AES-256-GCM加密数据，返回 nonce(12) + ciphertext + tag(16)"""
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return nonce + ciphertext + tag

def decrypt_data(encrypted: bytes, key: bytes) -> bytes:
    """解密数据，输入格式同上。支持空明文（密文长度为 0）的边界情况。"""
    if len(key) != 32:
        raise ValueError("无效的 AES-256 密钥长度")
    if len(encrypted) < 28:
        raise ValueError("加密数据已截断")
    nonce = encrypted[:12]
    tag = encrypted[-16:]
    ciphertext = encrypted[12:-16]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    if not ciphertext:
        # 空明文：只校验 tag，验证通过即返回空字节串
        cipher.verify(tag)
        return b''
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return plaintext

def generate_key():
    return os.urandom(32)
