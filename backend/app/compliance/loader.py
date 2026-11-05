"""制裁名单加载与解析（PRD F6 L1：OFAC SDN 真实公开数据）。

支持两种来源：
- `sdn.csv` + `alt.csv`（OFAC 官方原始文件，无表头）
- `entries.json`（本项目解析后的缓存，避免每次启动重复解析）

注意：本机 TLS 被本地代理拦截（自签名证书），下载需要 `--insecure`；
因此下载后必须做**内容校验**（行数、字段数、SHA256 打印），不能只靠证书。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

LIST_NAME = "OFAC SDN"

# sdn.csv 的 12 列：ent_num, sdn_name, sdn_type, program, title, call_sign,
# vessel_type, tonnage, grt, flag, owner, remarks
SDN_COLUMNS = 12

# remarks 里的别名：a.k.a. 'XXX' / a.k.a. "XXX"
_AKA_RE = re.compile(r"a\.k\.a\.\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)


@dataclass
class SanctionRecord:
    entry_no: str
    name: str
    aliases: list[str] = field(default_factory=list)
    program: str | None = None
    country: str | None = None
    list_name: str = LIST_NAME

    def to_dict(self) -> dict:
        return {
            "entry_no": self.entry_no,
            "name": self.name,
            "aliases": self.aliases,
            "program": self.program,
            "country": self.country,
            "list_name": self.list_name,
        }


def _clean(value: str | None) -> str:
    v = (value or "").strip()
    return "" if v in ("-0-", "-0- ", "") else v


def parse_sdn(sdn_text: str, alt_text: str | None = None) -> list[SanctionRecord]:
    """解析 sdn.csv（+ 可选 alt.csv），返回去重后的条目列表。"""
    aliases_by_entry: dict[str, list[str]] = {}
    if alt_text:
        for row in csv.reader(io.StringIO(alt_text)):
            if len(row) < 4:
                continue
            ent_no, _alt_no, alt_type, alt_name = row[0], row[1], row[2], row[3]
            alt_name = _clean(alt_name)
            if not alt_name:
                continue
            if (alt_type or "").strip().lower() in ("aka", "fka", "nka"):
                aliases_by_entry.setdefault(ent_no.strip(), []).append(alt_name)

    records: list[SanctionRecord] = []
    seen: set[str] = set()
    for row in csv.reader(io.StringIO(sdn_text)):
        if len(row) < SDN_COLUMNS:
            continue
        ent_no = _clean(row[0])
        name = _clean(row[1])
        if not ent_no or not name or ent_no in seen:
            continue
        seen.add(ent_no)

        aliases = list(aliases_by_entry.get(ent_no, []))
        aliases.extend(_AKA_RE.findall(row[11] or ""))
        # 去重保序，并排除与主名相同的别名
        uniq: list[str] = []
        for alias in aliases:
            alias = _clean(alias)
            if alias and alias.lower() != name.lower() and alias not in uniq:
                uniq.append(alias)

        records.append(
            SanctionRecord(
                entry_no=ent_no,
                name=name,
                aliases=uniq,
                program=_clean(row[3]) or None,
            )
        )

    logger.info("解析 OFAC SDN 条目 %d 条", len(records))
    return records


def save_json(records: list[SanctionRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.to_dict() for r in records], ensure_ascii=False),
        encoding="utf-8",
    )


def load_json(path: Path) -> list[SanctionRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        SanctionRecord(
            entry_no=item["entry_no"],
            name=item["name"],
            aliases=item.get("aliases", []),
            program=item.get("program"),
            country=item.get("country"),
            list_name=item.get("list_name", LIST_NAME),
        )
        for item in raw
    ]


def save_to_db(session, records: list[SanctionRecord]) -> int:
    """写入 sanctions_entries 表（先清空旧数据，保证幂等）。"""
    from sqlalchemy import delete

    from app.db.models import SanctionEntry as SanctionEntryRow

    session.execute(delete(SanctionEntryRow))
    for record in records:
        session.add(
            SanctionEntryRow(
                list_name=record.list_name,
                entry_no=record.entry_no,
                name=record.name,
                name_norm=normalize_name(record.name),
                aliases=record.aliases,
                program=record.program,
                country=record.country,
            )
        )
    session.commit()
    logger.info("写入 sanctions_entries %d 条", len(records))
    return len(records)


def load_from_db(session) -> list[SanctionRecord]:
    from sqlalchemy import select

    from app.db.models import SanctionEntry as SanctionEntryRow

    rows = session.scalars(select(SanctionEntryRow)).all()
    return [
        SanctionRecord(
            entry_no=row.entry_no,
            name=row.name,
            aliases=list(row.aliases or []),
            program=row.program,
            country=row.country,
            list_name=row.list_name,
        )
        for row in rows
    ]


_TOKEN_RE = re.compile(r"[A-Z0-9]+")
_STOPWORDS = {
    "THE", "AND", "OF", "CO", "COMPANY", "LTD", "LIMITED", "INC", "LLC",
    "CORP", "CORPORATION", "GROUP", "HOLDING", "HOLDINGS", "TRADING", "TRADE",
    "IMPORT", "EXPORT", "INDUSTRIES", "INDUSTRY", "INTL", "INTERNATIONAL",
    "BUSINESS", "SERVICES", "SUPPLIES", "SUPPLY", "SOLUTIONS", "TECHNOLOGIES", "S",
}


def normalize_name(value: str | None) -> str:
    """归一化公司名：大写、去标点、压缩空白。"""
    text = re.sub(r"[^\w\s]", " ", (value or "").upper())
    return re.sub(r"\s+", " ", text).strip()


def meaningful_tokens(value: str | None) -> list[str]:
    return [t for t in _TOKEN_RE.findall(normalize_name(value)) if t not in _STOPWORDS]
