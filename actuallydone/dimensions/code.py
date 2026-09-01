"""维度：代码质量。

只做静态扫描，不重跑测试。覆盖率缺口复用门禁留下的 profile。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..adapters import CAP_COVERAGE, CAP_FUNCS, get
from ..extractors import EXTRACTORS, extract, sql_dropped_tables
from ..model import DimResult, Metric
from ..textio import read as read_source


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("code", "代码质量")
    checked = 0

    checked += _consistency(cfg, res)
    checked += _unused(cfg, res)
    dups = _dups(cfg, res)
    big, marks = _size_and_marks(cfg, res)
    cover = _coverage_gap(cfg, res)

    if checked == 0 and dups is None and cover is None and not big:
        return res.skip("没有可做的代码检查：没配 consistency.pair / code.unused / "
                        "code.dup_roots / code.big_file_globs，适配器也提供不了函数切分")

    # 一致性与未引用符号的指标是逐条配出来的，已经在上面 append 过了，这里只补固定项
    res.metrics.extend(m for m in (
        (None if cfg.get("consistency.pair")
         else Metric("权威一致性", "未评估", "没配 consistency.pair")),
        Metric("重复函数体", f"{len(dups)} 组" if dups is not None else "未评估",
               f"归一化后完全相同，阈值 ≥{cfg.get('code.dup_min_lines')} 行"
               if dups is not None else "适配器切不出函数体",
               "good" if dups == [] else "warnv" if dups else ""),
        Metric("超大文件", str(len(big)) if cfg.get("code.big_file_globs") else "未评估",
               f"> {cfg.get('code.big_file_lines')} 行"
               if cfg.get("code.big_file_globs") else "没配 code.big_file_globs"),
        Metric("遗留标记", str(marks) if cfg.get("code.mark_globs") else "未评估",
               "/".join(cfg.get("code.mark_words", []))
               if cfg.get("code.mark_globs") else "没配 code.mark_globs"),
        Metric("零覆盖函数", f"{cover[0]}/{cover[1]}" if cover else "未评估",
               "读门禁留下的 profile，不重跑测试" if cover
               else "没有 profile 或适配器不支持"),
    ) if m)
    res.notes.append("「权威对权威」的一致性在这里判（两份都自称权威全量，必须完全一致）；"
                     "「选摘查幻影」在 AI 物料维度判（文档只是摘录，不要求全覆盖）。")
    return res


def _consistency(cfg, res: DimResult) -> int:
    """两份都自称权威全量的文件必须一致。不一致是错误级——它会让两条路径长出两个不同的世界。"""
    pairs = cfg.get("consistency.pair", []) or []
    for pair in pairs:
        a_rel, b_rel = pair.get("a"), pair.get("b")
        kind = pair.get("extract", "sql_tables")
        if not (a_rel and b_rel) or kind not in EXTRACTORS:
            res.add("警告", "adone.toml",
                    f"consistency.pair 配置不完整或 extract={kind} 不认识，"
                    f"可用：{'/'.join(EXTRACTORS)}")
            continue
        a, b = cfg.root / a_rel, cfg.root / b_rel
        sa, sb = extract(kind, a) or set(), extract(kind, b) or set()
        only_a, only_b = sorted(sa - sb), sorted(sb - sa)
        label = pair.get("label") or f"{a_rel} ↔ {b_rel}"

        if only_a:
            res.add("错误", b_rel,
                    f"{len(only_a)} 项只在 {a_rel} 里有，{b_rel} 缺："
                    + "、".join(only_a[:10]) + ("…" if len(only_a) > 10 else ""))
        # 一处显式删掉、另一处还在建，是最容易漏的一种漂移
        dropped = sql_dropped_tables(a) if kind == "sql_tables" else set()
        for t in only_b:
            if t in dropped:
                res.add("错误", b_rel,
                        f"{t} 已被 {a_rel} 显式删除，{b_rel} 却仍在建，两边会长出不同的结构")
        rest = [t for t in only_b if t not in dropped]
        if rest:
            res.add("错误", a_rel,
                    f"{len(rest)} 项只在 {b_rel} 里有，{a_rel} 缺："
                    + "、".join(rest[:10]) + ("…" if len(rest) > 10 else ""))

        res.metrics.append(Metric(
            label.split("↔")[0].strip().split("/")[-1] + " 一致性",
            f"{len(sa)} / {len(sb)}",
            "一致" if not only_a and not only_b else f"差 {len(only_a) + len(only_b)} 项",
            "good" if not only_a and not only_b else "bad"))
    return len(pairs)


def _unused(cfg, res: DimResult) -> int:
    """定义了却没人引用的符号。用「定义正则 + 使用正则」表达，与语言无关。"""
    rules = cfg.get("code.unused", []) or []
    for rule in rules:
        define = rule.get("define")
        use = rule.get("use")
        glob = rule.get("glob")
        if not (define and use and glob):
            res.add("警告", "adone.toml", "code.unused 规则要同时有 glob / define / use")
            continue
        def_re, use_re = re.compile(define, re.M), re.compile(use)
        defined: dict[str, str] = {}
        used: set[str] = set()
        for p in sorted(cfg.root.glob(glob)):
            text = read_source(p)
            for name in def_re.findall(text):
                defined[name if isinstance(name, str) else name[0]] = p.name
            used |= {n if isinstance(n, str) else n[0] for n in use_re.findall(text)}
        dead = sorted(n for n in defined if n not in used)
        name = rule.get("name", "未引用符号")
        if dead:
            res.add(rule.get("severity", "警告"), glob,
                    f"{len(dead)} 个{name}定义了但没被任何地方引用："
                    + "、".join(dead[:8]) + ("…" if len(dead) > 8 else ""))
        res.metrics.append(Metric(name, str(len(dead)), f"共定义 {len(defined)} 个",
                                  "good" if not dead else "warnv"))
    return len(rules)


def _dups(cfg, res: DimResult) -> list | None:
    roots = cfg.get("code.dup_roots", []) or []
    if not roots:
        return None
    min_lines = int(cfg.get("code.dup_min_lines", 8))
    buckets: dict[str, list[str]] = {}
    any_cap = False
    for eco in cfg.ecosystems or ["generic"]:
        ad = get(eco, cfg.root)
        if CAP_FUNCS not in ad.caps:
            continue
        any_cap = True
        for root in roots:
            base = cfg.root / root
            if not base.is_dir():
                continue
            for f in sorted(base.rglob("*")):
                if not f.is_file() or f.suffix not in ad.source_exts:
                    continue
                if any(k in f.name for k in ("_test.", ".test.", ".spec.")):
                    continue
                for fn in ad.iter_funcs(f):
                    if len(fn.body) < min_lines:
                        continue
                    digest = hashlib.sha1("\n".join(fn.body).encode()).hexdigest()
                    buckets.setdefault(digest, []).append(
                        f"{f.relative_to(cfg.root)}:{fn.line} {fn.name}")
    if not any_cap:
        return None
    dups = [v for v in buckets.values() if len(v) > 1]
    if dups:
        s = dups[0]
        res.add("警告", "、".join(roots),
                f"{len(dups)} 组归一化后完全相同的函数体，例如 {s[0]} 与 {s[1]}")
    return dups


def _size_and_marks(cfg, res: DimResult) -> tuple[list[str], int]:
    limit = int(cfg.get("code.big_file_lines", 800))
    big: list[tuple[str, int]] = []
    for pat in cfg.get("code.big_file_globs", []) or []:
        for f in cfg.root.glob(pat):
            if not f.is_file():
                continue
            n = len(read_source(f).splitlines())
            if n > limit:
                big.append((str(f.relative_to(cfg.root)), n))
    if big:
        top = sorted(big, key=lambda t: -t[1])[:3]
        res.add("提示", "体积", f"{len(big)} 个文件超过 {limit} 行，最大的几个："
                + "、".join(f"{p}（{n} 行）" for p, n in top))

    words = cfg.get("code.mark_words", []) or []
    mark_re = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b") \
        if words else None
    marks = 0
    if mark_re:
        for pat in cfg.get("code.mark_globs", []) or []:
            for f in cfg.root.glob(pat):
                if f.is_file():
                    marks += len(mark_re.findall(read_source(f)))
    return [p for p, _ in big], marks


def _coverage_gap(cfg, res: DimResult) -> tuple[int, int] | None:
    profile: Path = cfg.cover_out
    ratio = float(cfg.get("code.zero_cover_ratio", 0.15))
    # profile 里的路径是相对模块根的，要在跑测试的那个目录里解析，不能在仓库根
    cwd = cfg.root
    for s in cfg.get("gate.step", []) or []:
        if s.get("kind") == "test":
            cwd = cfg.root / s.get("cwd", ".")
            break
    for eco in cfg.ecosystems or []:
        ad = get(eco, cfg.root)
        if CAP_COVERAGE not in ad.caps:
            continue
        got = ad.zero_cover(profile, cwd)
        if got is None:
            continue
        zero, total = got
        if total and zero / total > ratio:
            res.add("警告", "覆盖率缺口",
                    f"{zero}/{total} 个函数覆盖率为 0%，超过 {ratio:.0%} 的观察阈值")
        return got
    return None
