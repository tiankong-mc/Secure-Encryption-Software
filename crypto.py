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
    """解密数据，输入格式同上"""
    nonce = encrypted[:12]
    tag = encrypted[-16:]
    ciphertext = encrypted[12:-16]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return plaintext

def generate_key():
    return os.urandom(32)
