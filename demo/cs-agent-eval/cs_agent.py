"""内存客服：召回、多块合并、是否打断。不引入 LangGraph。

知识来自 `.cursor/skills/**/*.md` 里以 `##` 切开的块，语义对应客服图里的
召回 / 合并 / HITL 节点，跑评测时不需要模型。
"""

from __future__ import annotations

import re
from pathlib import Path

HEADING_RE = re.compile(r"^## ", re.M)
KW_RE = re.compile(r"^关键词：\s*(.+)$", re.M)
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元")
LOGISTICS_MARKS = ("物流", "快递", "运单", "到哪了")


def load_blocks(root: Path) -> list[dict]:
    skills = root / ".cursor" / "skills"
    blocks: list[dict] = []
    if not skills.is_dir():
        return blocks
    for p in sorted(skills.rglob("*.md")):
        text = p.read_text(encoding="utf-8")
        parts = HEADING_RE.split(text)
        for part in parts[1:]:
            title, _, body = part.partition("\n")
            title = title.strip()
            body = body.strip()
            kws = []
            m = KW_RE.search(body)
            if m:
                kws = [x.strip() for x in m.group(1).split("、") if x.strip()]
            blocks.append({
                "id": title,
                "title": title,
                "body": body,
                "keywords": kws,
                "prefer_on_conflict": "冲突时取本块" in body,
                "forbid_interrupt": "禁止打断" in body,
                "require_interrupt": "必须打断" in body,
            })
    return blocks


def recall(query: str, blocks: list[dict]) -> list[dict]:
    hits: list[dict] = []
    for b in blocks:
        keys = list(b["keywords"]) or [b["title"]]
        if any(k and k in query for k in keys):
            hits.append(b)
    return hits


def merge(hits: list[dict]) -> str:
    if not hits:
        return ""
    preferred = [b for b in hits if b["prefer_on_conflict"]]
    return (preferred[0] if preferred else hits[0])["id"]


def parse_amount(query: str) -> float | None:
    m = AMOUNT_RE.search(query)
    return float(m.group(1)) if m else None


def should_interrupt(query: str, hits: list[dict], amount: float | None) -> bool:
    if any(mark in query for mark in LOGISTICS_MARKS):
        return False
    if any(b["forbid_interrupt"] for b in hits):
        return False
    if amount is not None and amount >= 1000:
        return True
    return any(b["require_interrupt"] for b in hits)


def run(root: Path, query: str, amount: float | None = None) -> dict:
    blocks = load_blocks(root)
    hits = recall(query, blocks)
    amt = amount if amount is not None else parse_amount(query)
    return {
        "hits": [b["id"] for b in hits],
        "merged": merge(hits),
        "interrupt": should_interrupt(query, hits, amt),
        "amount": amt,
    }
