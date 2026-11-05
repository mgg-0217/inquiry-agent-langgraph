"""下载并解析 OFAC SDN 制裁名单（PRD F6 L1 / 17.2）。

用法：
    python scripts/fetch_sanctions.py --out backend/data/sanctions/
    python scripts/fetch_sanctions.py --out backend/data/sanctions/ --insecure   # 本机 TLS 被代理拦截时
    python scripts/fetch_sanctions.py --out backend/data/sanctions/ --load      # 同时写入数据库

产物：
    <out>/sdn.csv        官方主表（约 19,000 条）
    <out>/alt.csv        官方别名表
    <out>/entries.json   解析后的条目（应用启动时自动导入 DB）

安全说明：本机有 TLS 中间人（自签名证书），--insecure 只跳过证书校验；
下载后必须看打印的 SHA256 与条目数，确认文件完整。
"""

from __future__ import annotations

import argparse
import hashlib
import ssl
import sys
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.compliance.loader import parse_sdn, save_to_db, save_json  # noqa: E402

BASE = "https://www.treasury.gov/ofac/downloads/"
URLS = {"sdn.csv": BASE + "sdn.csv", "alt.csv": BASE + "alt.csv"}


def download(url: str, dest: Path, insecure: bool) -> tuple[str, int]:
    context = ssl._create_unverified_context() if insecure else None
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 inquiry-agent"})
    with urllib.request.urlopen(request, timeout=180, context=context) as response:
        data = response.read()
    dest.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 OFAC SDN 名单")
    parser.add_argument("--out", default="backend/data/sanctions", help="输出目录")
    parser.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验（本机代理拦截时用）")
    parser.add_argument("--load", action="store_true", help="解析后写入数据库")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    contents: dict[str, str] = {}
    for filename, url in URLS.items():
        try:
            digest, size = download(url, out / filename, args.insecure)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 下载失败 {url}: {exc}")
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                print("   本机 TLS 被代理拦截，重试：--insecure")
            return 1
        contents[filename] = (out / filename).read_text(encoding="utf-8", errors="replace")
        print(f"✅ {filename}: {size:,} bytes  sha256={digest}")

    records = parse_sdn(contents["sdn.csv"], contents["alt.csv"])
    if not records:
        print("❌ 解析结果为空，文件可能不是预期的 SDN CSV")
        return 1

    json_path = out / "entries.json"
    save_json(records, json_path)
    with_alias = sum(1 for r in records if r.aliases)
    print(f"✅ 解析条目 {len(records):,} 条（含别名 {with_alias:,} 条）→ {json_path}")

    if args.load:
        from app.db.migrate import run_migrations
        from app.db.session import SessionLocal

        run_migrations()
        with SessionLocal() as session:
            count = save_to_db(session, records)
        print(f"✅ 已写入数据库 sanctions_entries：{count:,} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
