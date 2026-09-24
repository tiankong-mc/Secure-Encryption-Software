import os

VERSION = "v2.5.0"
WEB_PORT = 8080
ISSUES_URL = "https://github.com/tiankong-mc/Secure-Encryption-Software/issues"
LANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")

ABOUT_TEXT = """SecureVault —— 一个专注于本地安全的加密文件保险库。

我希望这个软件能成为你数字生活中一个小小的"保险柜"：
文件加密与解密在本机完成，不会上传明文文件。
仅在你主动使用邮箱验证、检查更新或局域网页面时联网。
验证配置与主密钥由 Windows DPAPI 加密后保存在本机。

本项目github链接为：github.com/tiankong-mc/Secure-Encryption-Software
作者B站主页为：space.bilibili.com/1974438557
作者爱发电主页为：ifdian.net/a/tiankong_mc
有能力的可以赞助一下，让TK更有动力

如果你觉得这个项目对你有帮助，
欢迎在 GitHub 上给个 Star，或者提交 Issue 告诉我你的想法。

—— tiankong
"""
