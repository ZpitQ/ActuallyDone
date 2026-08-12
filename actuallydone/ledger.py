"""需求台账：跨迭代的那本账，每条需求绑几个证据锚点，由脚本去核。

它抓的不是「还没做完」，而是**失联需求**——标了已做，但绑的表/路由/用例已经不在了。
曾经做过、如今证据没了，这才是真正的偏离。所以覆盖率低不扣分，失联才扣。
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from .config import Config
from .extractors import route_known, sql_tables

VALID_STATUS = ("done", "partial", "todo", "dropped")
ANCHOR_KINDS = ("table", "route", "test", "view", "file", "skill", "adr")

SECTION_RE = re.compile(r"^\s*(#{1,3})\s+(.*)$")   # 需求源里有缩进过的标题，别漏
BULLET_RE = re.compile(r"^(\s*)(?:[-*]|\d+[.)])\s+(.*)$")
DONE_MARK = "✅"


def build_anchor_index(cfg: Config) -> dict:
    """建锚点索引。取不到的类别置 None，核验时报「无法核验」而不是「不存在」。"""
    from .adapters import CAP_ROUTES, CAP_TESTS, CAP_VIEWS, get
    from .gate import load_latest

    receipt = load_latest(cfg) or {}
    passed = set(receipt.get("tests", {}).get("passed_names", []))

    idx: dict = {"passed": {n.split("/")[0] for n in passed}}

    tf = cfg.get("requirements.tables_from")
    idx["tables"] = sql_tables(cfg.root / tf) if tf else None

    ad = get(cfg.get("tests.adapter") or "", cfg.root)
    rf = cfg.get("requirements.routes_from")
    idx["routes"] = (ad.routes(cfg.root / rf)
                     if rf and CAP_ROUTES in ad.caps else None)

    roots = [cfg.root / r for r in (cfg.get("tests.roots", []) or [])]
    idx["tests"] = ad.test_names(roots) if CAP_TESTS in ad.caps else None

    vf = cfg.get("requirements.views_from")
    view_ad = get("node", cfg.root)
    idx["views"] = (view_ad.views(cfg.root / vf)
                    if vf and CAP_VIEWS in view_ad.caps else None)

    idx["skills"] = ({d.name for d in cfg.skills_dir.iterdir()
                      if d.is_dir() and (d / "SKILL.md").exists()}
                     if cfg.skills_dir.is_dir() else None)

    adr_dir = cfg.get("docs.adr_dir")
    idx["adrs"] = ({p.stem for p in (cfg.root / adr_dir).glob("*.md")}
                   if adr_dir and (cfg.root / adr_dir).is_dir() else None)
    return idx


def verify_anchor(cfg: Config, anchor: str, idx: dict) -> tuple[str, str]:
    """校验一条证据锚点，返回 (级别, 说明)；级别为空串表示有效。"""
    kind, _, val = anchor.partition(":")
    kind, val = kind.strip(), val.strip()
    if kind not in ANCHOR_KINDS:
        return "警告", f"未知的锚点类型「{kind}」，可用：{'/'.join(ANCHOR_KINDS)}"

    if kind == "file":
        return ("", "") if (cfg.root / val).exists() else ("错误", f"文件 {val} 不存在")

    pool_key = {"table": "tables", "route": "routes", "test": "tests",
                "view": "views", "skill": "skills", "adr": "adrs"}[kind]
    pool = idx.get(pool_key)
    if pool is None:
        return "警告", (f"{kind}: 类锚点无法核验——没配对应来源"
                        f"（requirements.{pool_key}_from 之类），这条证据等于没查")

    if kind == "route":
        path = val.split(None, 1)[-1] if " " in val else val   # 允许写「GET /x」
        return ("", "") if route_known(path, pool) else ("错误", f"路由 {val} 在代码里找不到注册")
    if kind == "test":
        if val not in pool:
            return "错误", f"用例 {val} 在测试源码里不存在"
        if idx.get("passed") and val not in idx["passed"]:
            return "警告", f"用例 {val} 存在，但没出现在最新回执的通过名单里"
        return "", ""
    label = {"table": "表", "view": "前端页面", "skill": "技能", "adr": "决策记录"}[kind]
    return ("", "") if val in pool else ("错误", f"{label} {val} 不存在")


def load_ledger(cfg: Config) -> list[tuple[Path, dict]]:
    d = cfg.requirements_dir
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.toml")):
        try:
            out.append((p, tomllib.loads(p.read_text(encoding="utf-8"))))
        except Exception as e:
            out.append((p, {"__error__": str(e)}))
    return out


# --------------------------------------------------------------------------- 骨架生成

def guess_anchors(text: str, idx: dict, keywords: dict[str, str],
                  limit: int = 3) -> list[str]:
    """给需求文本猜几个证据候选。只作候选，不冒充证据。"""
    toks = {en for zh, en in keywords.items() if zh in text}
    for word in re.findall(r"[A-Za-z][A-Za-z_/]{2,}", text):
        toks.add(word.lower())
    if not toks:
        return []

    def best(pool: set[str] | None, t: str) -> str | None:
        """前缀命中优先于包含命中：listing 该配 listing_tasks，不该配 composite_listing。"""
        if not pool:
            return None
        low = {c: c.lower() for c in pool}
        for pick in (lambda c: low[c] == t, lambda c: low[c].startswith(t),
                     lambda c: t in low[c]):
            got = sorted(c for c in pool if pick(c))
            if got:
                return got[0]
        return None

    hits: list[str] = []
    for t in sorted(toks):
        for kind, key in (("table", "tables"), ("test", "tests")):
            got = best(idx.get(key), t)
            if got and f"{kind}:{got}" not in hits:
                hits.append(f"{kind}:{got}")
        if len(hits) >= limit:
            break
    return hits[:limit]


def safe_name(title: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title).strip("-")
    return s[:24] or "section"


def toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"')[:300] + '"'


def init_ledger(cfg: Config, force: bool = False) -> int:
    src_rel = cfg.get("requirements.source")
    if not src_rel:
        print("没配 requirements.source（需求源文档），无从生成台账", file=sys.stderr)
        return 2
    src = cfg.root / src_rel
    if not src.exists():
        print(f"找不到需求源 {src_rel}", file=sys.stderr)
        return 2

    cfg.requirements_dir.mkdir(parents=True, exist_ok=True)
    idx = build_anchor_index(cfg)
    keywords = cfg.get("requirements.keywords", {}) or {}

    lines = src.read_text(encoding="utf-8").splitlines()
    sections: list[tuple[str, list[tuple[int, str, bool]]]] = []
    cur, bag = "未分类", []
    for no, ln in enumerate(lines, 1):
        m = SECTION_RE.match(ln)
        if m and m.group(1) == "#":
            if bag:
                sections.append((cur, bag))
            cur = m.group(2).strip().replace(DONE_MARK, "").strip() or f"第 {no} 行"
            bag = []
            continue
        b = BULLET_RE.match(ln)
        if b:
            text = b.group(2).strip()
            if len(text) < 4:
                continue
            bag.append((no, text.replace(DONE_MARK, "").strip(), DONE_MARK in text))
    if bag:
        sections.append((cur, bag))
    if not sections:
        print(f"{src_rel} 里没解析出任何条目（需求源要用 markdown 标题 + 列表）",
              file=sys.stderr)
        return 2

    written, n_items = [], 0
    for si, (title, items) in enumerate(sections, 1):
        out = cfg.requirements_dir / f"{si:02d}-{safe_name(title)}.toml"
        if out.exists() and not force:
            print(f"  跳过已存在的 {out.relative_to(cfg.root)}（要覆盖加 --force）")
            continue
        body = [
            "# 需求台账：由 adone requirements init 从需求源生成的骨架。",
            "# 状态需要人工校对；证据候选是机器猜的，确认后把它挪到 证据 = [...] 里才算数。",
            f"# 锚点：{' / '.join(k + ':' for k in ANCHOR_KINDS)}",
            "# 中文键一律加引号：TOML 的裸键只允许 ASCII 字母数字与 _ - ，不加引号会解析失败。",
            "",
            f'"源" = "{src_rel}"',
            f'"章节" = {toml_str(title)}',
            "",
        ]
        for i, (no, text, done) in enumerate(items, 1):
            cands = guess_anchors(text, idx, keywords)
            body += [
                "[[item]]",
                f'id = "S{si}-{i:03d}"',
                f'"需求" = {toml_str(text)}',
                f'"源位置" = "{src_rel}:{no}"',
                f'"状态" = "{"done" if done else "todo"}"',
                '"证据" = []',
            ]
            if cands:
                body.append('"证据候选" = [' + ", ".join(f'"{c}"' for c in cands) + "]")
            body.append("")
            n_items += 1
        out.write_text("\n".join(body), encoding="utf-8")
        written.append(out.relative_to(cfg.root))

    for w in written:
        print(f"  写入 {w}")
    print(f"共 {n_items} 条需求，分 {len(written)} 份台账。"
          f"下一步：人工校对「状态」，把确认过的证据候选挪进「证据」。")
    return 0


def cmd_requirements(cfg: Config, args) -> int:
    if args.sub == "init":
        return init_ledger(cfg, force=args.force)

    from .dimensions.requirements import run as run_dim
    res = run_dim(_MiniCtx(cfg))
    for m in res.metrics:
        print(f"  {m.label}: {m.value}  {m.sub}")
    if res.findings:
        print()
        for f in sorted(res.findings, key=lambda x: x.severity):
            print(f"  [{f.severity}] {f.where}  {f.message}")
    return 1 if res.errors else 0


class _MiniCtx:
    """维度函数只用到 cfg 与两个开关，命令行单跑时给个最小实现。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.run_gate = False
        self.with_probes = False
