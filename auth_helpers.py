"""验证相关的共享工具函数与常量。

将邮箱验证码的 TTL、恒定时间比较逻辑集中在此，
避免 ui_dialogs.py 与 ui_login.py 各自维护一份重复实现，
未来修改 TTL 只需改这一处。
"""

import time
import secrets


# 邮箱验证码有效期（秒）
EMAIL_CODE_TTL = 300


def verify_email_code(input_value, expected_code, code_time):
    """
    校验邮箱验证码。

    参数：
      input_value   - 用户输入的内容
      expected_code - 发送过的验证码（None 表示尚未发送）
      code_time     - 发送验证码时记录的时间戳（time.time()）

    返回：
      (status, message)
      status:
        'ok'      - 校验通过
        'fail'    - 校验失败（信息不匹配）
        'no_code' - 尚未点击“发送验证码”
        'expired' - 验证码已超过有效期
      message: 仅当 status 为 'no_code' / 'expired' 时提供提示文本，否则为 None
    """
    if expected_code is None:
        return 'no_code', "请先点击“发送验证码”获取验证码"
    if time.time() - code_time > EMAIL_CODE_TTL:
        return 'expired', "验证码已过期，请重新发送"
    if secrets.compare_digest(str(input_value), str(expected_code)):
        return 'ok', None
    return 'fail', None
