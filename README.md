# SecureVault

> 🔐 一个专注于本地安全的开源文件加密保险库
>
> AES-256-GCM 加密 · 多因素验证 · 内置安全预览 · 完全离线运行

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/PyQt5-5.15+-green.svg)](https://pypi.org/project/PyQt5/)
[![License](https://img.shields.io/badge/License-GPLv3-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)]()

---

## ✨ 特性

### 🔒 核心加密
- **AES-256-GCM** 认证加密，与银行、军方同标准
- **一文件一密钥**：每个文件独立生成 256 位随机密钥
- **主密钥保护**：文件密钥由主密钥封装，主密钥受 Windows DPAPI 保护，绑定当前 Windows 用户账户与电脑硬件
- **自定义 `.vault` 格式**：`MAGIC + VERSION + 密钥长度 + 加密的文件密钥 + 加密内容`，不再依赖 pickle，杜绝反序列化攻击
- **严格完整性校验**：GCM 认证标签确保密文哪怕改动 1 字节都会解密失败

### 🛡️ 多因素验证
登录和敏感操作可自由组合以下任意验证方式（至少启用一种）：
- **密码**（bcrypt 哈希存储）
- **安全问题**（3 组问答，可跳过）
- **TOTP**（兼容 Microsoft Authenticator / Google Authenticator）
- **邮箱验证码**（SMTP 发送，一次性）
- **紧急恢复代码**（20 位随机字符串，使用一次即作废）

每种验证方式均可单独**启用/禁用**，禁用不删除配置，下次启用可直接复用。

### 🗂️ 文件管理
- **上传加密**：支持拖拽上传、批量选择，自动加密到 `.vault`
- **内置预览**：文本 / 图片 / 视频 / 音频 / DOCX / PDF
- **高级文件**：可标记为"二次验证文件"，打开时额外验证一次
- **虚拟标签**：给文件打标签，按标签筛选
- **双向存储**：秘密存储（隐藏目录）+ 用户指定位置双备份
- **导出解密**：验证身份后导出为明文

### 📱 移动端网页版
- 局域网内手机扫码访问，无需安装 App
- 网页端同样需要验证（支持密码 / 安全问题 / TOTP / 邮箱）
- 高级文件在网页端也要二次验证
- 只能在局域网访问，自动阻断公网来源
- 可手动开启 / 停止服务

### 🎨 界面与体验
- **深色 / 明亮**主题自由切换
- **多语言**：简体中文 / English / 日本語，支持导入自定义语言包（JSON 格式）
- **截屏防护**：启用后，任何截屏工具只能截到黑屏
- **日志系统**：记录所有操作（不记录密码和密钥），可查看、导出、清空
- **侧边栏设置界面**：安全、网页端、个性化、语言、反馈、检查更新、关于

### 🔄 安全与备份
- **错误 5 次自动锁定**：登录或二次验证连续错误 5 次，立即关闭验证窗口
- **保险库备份**：导出加密文件与索引为 `.vaultbk`，可与现有保险库合并导入
- **跨电脑迁移**：设置备份密码后，可在不同电脑 / Windows 账户间迁移
- **索引自动恢复**：主索引损坏时自动从 `.bak` 恢复
- **原子写入**：所有配置和索引都采用"写临时文件 → fsync → 原子替换"

### ⚙️ 其它
- **加密文件目录可自定义**：安装向导和设置页均可修改
- **配置文件和主密钥固定保存在系统默认位置**，防止用户误改导致安全性降低
- **检查更新**：从 GitHub Releases 自动检查并下载新版（支持断点续传、SHA-256 校验、SSL 分级降级）

---

## 🚀 快速开始

### 方式一：使用打包好的 exe（推荐普通用户）

从 [Releases](https://github.com/tiankong-mc/Secure-Encryption-Software/releases) 页面下载最新的 `Encryption.exe`，双击运行即可。

**首次启动会引导你设置**：
- 加密文件存储位置（可保持默认）
- 至少一种验证方式（密码 / 安全问题 / TOTP / 邮箱）

**系统要求**：Windows 10 / 11

### 方式二：从源码运行（开发者）

**环境要求**：Python 3.10+，Windows 10/11

```bash
# 1. 克隆仓库
git clone https://github.com/tiankong-mc/Secure-Encryption-Software.git
cd Secure-Encryption-Software

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
python main.py
```

---

## 📦 打包发布

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 打包（会自动带上 lang 语言包）
python -m PyInstaller --onefile --windowed --name Encryption --icon=myicon_1.ico --add-data "lang;lang" main.py

# 3. 产物在 dist/Encryption.exe
```

也可以直接双击项目根目录的 `封装.bat`。

---

## 🗂️ 项目结构

```
Secure-Encryption-Software/
├── main.py                        # 入口
├── constants.py                   # 全局常量（版本号、URL、关于文案）
├── requirements.txt
├── 封装.bat                        # 一键打包脚本
│
├── crypto.py                      # AES-256-GCM 加密核心
├── auth.py                        # 验证管理（密码 / 问题 / TOTP / 邮箱 / 恢复码）
├── settings.py                    # 配置管理（DPAPI 加密 + 加密文件目录）
├── storage.py                     # 保险库存储、索引、备份导入导出
├── backup.py                      # 邮件备份辅助
├── i18n.py                        # 国际化
├── updater.py                     # 检查更新、断点续传下载
│
├── ui.py                          # UI 入口（重新导出）
├── ui_main.py                     # 主窗口
├── ui_login.py                    # 登录 + 首次设置向导
├── ui_settings.py                 # 设置主对话框
├── ui_viewer.py                   # 文件预览器
├── ui_log.py                      # 日志窗口
├── ui_dialogs.py                  # 通用对话框
├── ui_web.py                      # 移动端 Flask 服务
├── ui_styles.py                   # 主题样式表
├── ui_utils.py                    # 截屏防护等工具
├── ui_settings_style.py           # 设置界面统一样式
│
├── ui_settings_pages/             # 设置子页面
│   ├── page_security.py           # 安全
│   ├── page_web.py                # 网页端
│   ├── page_appearance.py         # 个性化
│   ├── page_language.py           # 语言
│   ├── page_update.py             # 检查更新
│   └── page_about.py              # 关于
│
└── lang/                          # 语言包
    ├── zh_CN.json                 # 简体中文
    ├── en_US.json                 # English
    └── ja_JP.json                 # 日本語
```

---

## 🛠️ 技术栈

| 层面 | 技术 |
|---|---|
| GUI | PyQt5 |
| 加密算法 | AES-256-GCM (pycryptodome) |
| 密钥保护 | Windows DPAPI |
| 密码哈希 | bcrypt |
| 动态口令 | pyotp |
| 二维码 | qrcode |
| 网络请求 | requests |
| 移动端服务 | Flask + Werkzeug |
| 文档解析 | python-docx + PyPDF2 |
| 图片处理 | Pillow |
| 打包 | PyInstaller |

---

## 📖 使用说明

### 首次启动
1. 设置加密文件目录（默认 `C:\ProgramData\SecureVault`，可修改）
2. 至少配置一种验证方式：
   - 密码：8 位以上
   - 安全问题：3 组问答
   - TOTP：扫描二维码绑定
   - 邮箱：配置 SMTP 并验证

### 日常使用
- **上传加密**：点击"上传加密"或拖拽文件到窗口
- **查看文件**：双击列表文件，高级文件需二次验证
- **移动端**：设置 → 网页端 → 启动服务 → 手机扫码
- **修改设置**：设置 → 安全 → 验证身份后修改

### 忘记密码怎么办？
1. 使用**紧急恢复代码**（设置 → 安全 → 生成）
2. 或者删除 `%APPDATA%\SecureVault` 重新配置（会丢失加密文件的索引，但加密文件本身仍在）

---

## ⚠️ 安全说明

### 已实现的安全措施
- AES-256-GCM 认证加密
- 每个文件独立密钥，主密钥由 DPAPI 保护
- 主密钥绑定 Windows 用户账户和电脑硬件，无法跨设备解密
- 不再使用 pickle 反序列化，杜绝代码执行风险
- 备份包路径穿越防护
- 网页端局域网访问限制 + 登录频率限制 + 验证码频率限制
- 索引和配置的原子写入
- 索引损坏自动从备份恢复
- 截屏防护基于 Windows API `SetWindowDisplayAffinity`

### 联网说明
程序**默认完全离线**。仅在以下场景会联网：
- 使用**邮箱验证码**时（SMTP 发送）
- 使用**移动端网页版**时（仅局域网）
- 主动点击**检查更新**时（GitHub API）

主密钥和验证配置**从不上传任何服务器**。

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

特别欢迎以下类型的贡献：
- 支持更多的文件预览格式
- 增加新的验证方式
- 界面美化 / 主题
- 更多语言包（只需按 `lang/zh_CN.json` 格式新建一个 JSON 文件）
- 打包 / 安装脚本优化
- Bug 修复

提交 PR 前请：
1. Fork 仓库
2. 创建分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目基于 [GNU General Public License v3.0](LICENSE) 开源。

这意味着：
- ✅ 可以自由使用、修改、分发
- ✅ 可以用于商业用途
- ⚠️ 衍生作品必须同样以 GPL v3 开源
- ⚠️ 必须保留原作者版权声明

---

## 🙏 致谢

- [PyQt5](https://pypi.org/project/PyQt5/) — GUI 框架
- [pycryptodome](https://www.pycryptodome.org/) — AES 加密库
- [bcrypt](https://pypi.org/project/bcrypt/) — 密码哈希
- [pyotp](https://pypi.org/project/pyotp/) — TOTP 动态口令
- [Flask](https://flask.palletsprojects.com/) — 移动端 Web 服务
- [Pillow](https://python-pillow.org/) — 图片处理
- [python-docx](https://python-docx.readthedocs.io/) — Word 文档解析
- [PyPDF2](https://pypdf2.readthedocs.io/) — PDF 解析

---

## ⭐ Star History

如果这个项目对你有帮助，欢迎点一个 Star ⭐！

[![Star History Chart](https://api.star-history.com/svg?repos=tiankong-mc/Secure-Encryption-Software&type=Date)](https://star-history.com/#tiankong-mc/Secure-Encryption-Software&Date)

---

## 📮 联系作者

- GitHub：[@tiankong-mc](https://github.com/tiankong-mc)
- B 站：[space.bilibili.com/1974438557](https://space.bilibili.com/1974438557)
- 爱发电：[ifdian.net/a/tiankong_mc](https://ifdian.net/a/tiankong_mc)

有能力的可以赞助一下，让 TK 更有动力 ⭐
