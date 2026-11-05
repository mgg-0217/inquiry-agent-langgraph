"""
QQ 邮箱 IMAP 连通性验证脚本

用法：
    python scripts/check_qq_imap.py 你的邮箱@qq.com 你的授权码

作用：
    验证 IMAP 能否登录、能否读收件箱，并输出最近的邮件列表。
    用于第 11 天真实邮箱联调前的快速自检。

注意：
    QQ 邮箱 / 163 邮箱 登录后必须发送 ID 命令，否则 SELECT 会报
    "Unsafe Login. Please contact kefu@188.com for help"
"""

import imaplib
import sys
from email.header import decode_header, make_header


def decode_mime(s):
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def check_imap(host, port, user, password, folder="INBOX", limit=5):
    print(f"连接 {host}:{port} ...")
    conn = imaplib.IMAP4_SSL(host, port, timeout=20)

    # 关键：注册并发送 ID 命令（QQ / 163 邮箱必需）
    imaplib.Commands["ID"] = ("AUTH", "SELECTED", "NONAUTH")
    try:
        conn._simple_command(
            "ID",
            '("name" "inquiry-agent" "version" "1.0" "vendor" "python")',
        )
        print("ID 命令已发送（QQ 邮箱必需）")
    except Exception as e:
        print(f"ID 命令发送失败（部分服务商不需要，可忽略）: {e}")

    print("登录中 ...")
    conn.login(user, password)
    print("✅ 登录成功")

    typ, data = conn.select(folder, readonly=True)
    if typ != "OK":
        raise RuntimeError(f"选择文件夹失败: {data}")
    total = int(data[0]) if data and data[0] else 0
    print(f"✅ 进入 {folder}，邮件总数: {total}")

    if total == 0:
        print("\n收件箱为空，建议先给这个邮箱发一封测试邮件再跑本脚本。")
        conn.logout()
        return

    typ, data = conn.search(None, "ALL")
    ids = data[0].split()
    print(f"\n最近 {min(limit, len(ids))} 封邮件：")
    for mid in ids[-limit:][::-1]:
        typ, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])")
        if typ != "OK":
            continue
        raw = msg_data[0][1].decode("utf-8", errors="replace")
        headers = {}
        for line in raw.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        print(f"  - 主题  : {decode_mime(headers.get('subject', '(无)'))}")
        print(f"    发件人: {decode_mime(headers.get('from', ''))}")
        print(f"    时间  : {headers.get('date', '')}")
        print(f"    Msg-ID: {headers.get('message-id', '')}")

    conn.logout()
    print("\n✅ IMAP 验证全部通过")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        print("示例: python scripts/check_qq_imap.py 123456@qq.com abcdefghijklmnop")
        sys.exit(2)

    user, password = sys.argv[1], sys.argv[2]
    if "@" not in user:
        print("❌ 账号要填完整邮箱地址，如 123456@qq.com")
        sys.exit(2)

    host = "imap.qq.com" if user.endswith("@qq.com") else "imap.163.com"
    port = 993

    try:
        check_imap(host, port, user, password)
    except imaplib.IMAP4.error as e:
        print(f"\n❌ IMAP 错误: {e}")
        print("\n常见原因：")
        print("  1. 密码填的是 QQ 密码，不是授权码")
        print("  2. 授权码已失效（重新生成一个）")
        print("  3. 没在设置里开启 IMAP/SMTP 服务")
        print("  4. 报 'Unsafe Login' → 说明 ID 命令没生效")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 连接失败: {type(e).__name__}: {e}")
        print("\n检查：网络是否可达 imap.qq.com:993")
        sys.exit(1)


if __name__ == "__main__":
    main()
