"""实体消歧打分（PRD F6）。

PRD 的加权公式是 `0.4*name + 0.3*country + 0.2*address + 0.1*alias`。
当前 SDN 公开数据没有结构化国别/地址（sdn.csv 只有 program），
因此实现为：**名称/别名相似度取最大值 + 国别命中加成**，
等接入地址数据后再恢复原加权。

业务权衡：制裁筛查**宁可错杀**（与 spam 相反），阈值由调用方决定。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.compliance.loader import SanctionRecord, meaningful_tokens, normalize_name

SIM_THRESHOLD = 0.6
COUNTRY_BONUS = 0.05
TOP_N = 5
# 只共享停用词（TRADING / LTD 之类）时最多算到这个分，避免"NewCo Trading"误中 "NEWTON TRADING"
NO_TOKEN_OVERLAP_CAP = 0.7

# program 字段里能直接映射到国别的部分
PROGRAM_COUNTRY: dict[str, str] = {
    "CUBA": "CU",
    "IRAN": "IR",
    "SYRIA": "SY",
    "RUSSIA": "RU",
    "UKRAINE": "UA",
    "NORTH KOREA": "KP",
    "DPRK": "KP",
    "VENEZUELA": "VE",
    "BELARUS": "BY",
    "MYANMAR": "MM",
    "SUDAN": "SD",
    "SOMALIA": "SO",
    "LIBYA": "LY",
    "YEMEN": "YE",
    "LEBANON": "LB",
    "IRAQ": "IQ",
    "AFGHANISTAN": "AF",
}


@dataclass
class ScreenHit:
    list_name: str
    entry_no: str
    name: str
    score: float
    matched_alias: str | None = None
    program: str | None = None
    country: str | None = None

    @property
    def evidence(self) -> str:
        alias = f"（别名命中：{self.matched_alias}）" if self.matched_alias else ""
        return (
            f"{self.list_name} #{self.entry_no} · {self.name}{alias} · "
            f"匹配分 {self.score:.2f}"
        )


class SanctionsIndex:
    """预计算归一化名称与 token 倒排，避免每次筛查都做全量字符串比对。"""

    def __init__(self, records: list[SanctionRecord]):
        self.records = records
        self.norms = [normalize_name(r.name) for r in records]
        self.alias_norms = [
            [normalize_name(a) for a in r.aliases] for r in records
        ]
        self.token_index: dict[str, set[int]] = defaultdict(set)
        for i, record in enumerate(records):
            for token in meaningful_tokens(record.name):
                self.token_index[token].add(i)
            for alias in record.aliases:
                for token in meaningful_tokens(alias):
                    self.token_index[token].add(i)

    def candidates(self, query: str) -> list[int]:
        tokens = set(meaningful_tokens(query))
        ids: set[int] = set()
        for token in tokens:
            ids |= self.token_index.get(token, set())
        if not ids:
            # 没有任何共享词：保守起见退回全量比对（宁可错杀）
            return list(range(len(self.records)))
        return list(ids)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    matcher = SequenceMatcher(None, a, b)
    # 用上界快速排除，避免对 1.9 万条名单逐条做完整比对
    if matcher.real_quick_ratio() < SIM_THRESHOLD:
        return 0.0
    if matcher.quick_ratio() < SIM_THRESHOLD:
        return 0.0
    return matcher.ratio()


def _country_of(program: str | None) -> str | None:
    if not program:
        return None
    upper = program.upper()
    for key, code in PROGRAM_COUNTRY.items():
        if key in upper:
            return code
    return None


def screen_name(
    name: str,
    records: list[SanctionRecord],
    *,
    country: str | None = None,
    index: SanctionsIndex | None = None,
) -> list[ScreenHit]:
    query_norm = normalize_name(name)
    if not query_norm:
        return []
    query_tokens = set(meaningful_tokens(name))
    idx = index or SanctionsIndex(records)

    hits: list[ScreenHit] = []
    for i in idx.candidates(name):
        record = idx.records[i]
        name_sim = _ratio(query_norm, idx.norms[i])

        alias_sim = 0.0
        matched_alias: str | None = None
        for alias, alias_norm in zip(record.aliases, idx.alias_norms[i]):
            sim = _ratio(query_norm, alias_norm)
            if sim > alias_sim:
                alias_sim = sim
                matched_alias = alias

        best = max(name_sim, alias_sim)
        if best < SIM_THRESHOLD:
            continue

        # 没有任何有意义 token 重叠时，多半是常见词碰巧相似：压低分数，避免误杀
        record_tokens = set(meaningful_tokens(record.name))
        for alias in record.aliases:
            record_tokens |= set(meaningful_tokens(alias))
        if not (query_tokens & record_tokens):
            best = min(best, NO_TOKEN_OVERLAP_CAP)

        score = best
        hit_country = record.country or _country_of(record.program)
        if country and hit_country and country.upper() == hit_country.upper():
            score = min(1.0, score + COUNTRY_BONUS)

        hits.append(
            ScreenHit(
                list_name=record.list_name,
                entry_no=record.entry_no,
                name=record.name,
                score=round(score, 4),
                matched_alias=matched_alias if alias_sim > name_sim else None,
                program=record.program,
                country=hit_country,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:TOP_N]
