"""维度：AI 物料——需求/设计/开发三个阶段，AI 干活要用的东西齐不齐、新不新、准不准。

这里只查「选摘对权威」：文档自述是摘录，不要求全覆盖，只抓**幻影**——
文档里写了、代码里根本没有。要求全等的那种一致性在代码质量维度判。
"""

from __future__ import annotations

import re

from ..extractors import extract, route_known
from ..model import DimResult, Metric
from ..textio import read as read_source


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("materials", "AI 物料")
    did_anything = False

    # --- 齐备性 ---
    required = cfg.get("docs.required", []) or []
    missing = [r for r in required if not (cfg.root / r).exists()]
    for m in missing:
        res.add("错误", m, "关键物料缺件，AI 起手就少一份上下文")
    if required:
        did_anything = True
        res.metrics.append(Metric("物料齐备", f"{len(required) - len(missing)}/{len(required)}",
                                  "缺：" + ("、".join(missing) if missing else "无"),
                                  "good" if not missing else "bad"))

    # --- 图过期：源文件比渲染图新 ---
    globs = cfg.get("docs.diagram_globs", []) or []
    ext = cfg.get("docs.diagram_render_ext", ".svg")
    stale, n_diagram = [], 0
    for g in globs:
        for src in sorted(cfg.root.glob(g)):
            n_diagram += 1
            rendered = src.with_suffix(ext)
            if not rendered.exists():
                res.add("警告", str(rendered.relative_to(cfg.root)), "只有源文件没有渲染图")
            elif src.stat().st_mtime > rendered.stat().st_mtime:
                stale.append(rendered.name)
    if stale:
        res.add("警告", "、".join(globs), f"{'、'.join(stale)} 比源文件旧，图已过期")
    if globs:
        did_anything = True
        res.metrics.append(Metric("架构图", f"{n_diagram} 张",
                                  "有过期：" + "、".join(stale) if stale else "渲染图都比源文件新",
                                  "warnv" if stale else "good"))

    # --- 选摘查幻影 ---
    for spec in cfg.get("docs.excerpt", []) or []:
        did_anything = True
        f_rel, a_rel = spec.get("file"), spec.get("against")
        kind = spec.get("extract", "sql_tables")
        if not (f_rel and a_rel):
            res.add("警告", "adone.toml", "docs.excerpt 要同时有 file 与 against")
            continue
        doc = extract(kind, cfg.root / f_rel)
        real = extract(kind, cfg.root / a_rel)
        if doc is None or real is None:
            res.add("警告", f_rel, f"extract={kind} 不认识，无法核验")
            continue
        phantom = sorted(doc - real)
        if phantom:
            res.add("错误", f_rel,
                    f"{len(phantom)} 项在 {a_rel} 里不存在（幻影）："
                    + "、".join(phantom[:8]) + ("…" if len(phantom) > 8 else ""))
        res.metrics.append(Metric(f"{f_rel.split('/')[-1]} 选摘", f"{len(doc)}/{len(real)}",
                                  f"{len(phantom)} 项幻影" if phantom else "无幻影",
                                  "bad" if phantom else "good"))

    # --- 文档里写的路由能不能对上注册 ---
    routes_spec = cfg.get("docs.routes", []) or []
    for spec in routes_spec:
        did_anything = True
        f_rel = spec.get("file")
        doc_paths = sorted(extract(spec.get("extract", "openapi_paths"),
                                   cfg.root / f_rel) or set())
        from ..adapters import CAP_ROUTES, get
        ad = get(cfg.get("tests.adapter") or "", cfg.root)
        rf = cfg.get("requirements.routes_from")
        if not rf or CAP_ROUTES not in ad.caps:
            res.add("警告", f_rel, "没配 requirements.routes_from 或适配器提不出路由，无法核验")
            continue
        literals = ad.routes(cfg.root / rf) or set()
        phantom = [p for p in doc_paths if not route_known(p, literals)]
        if phantom:
            res.add("警告", f_rel,
                    f"{len(phantom)} 条路径在代码里找不到注册"
                    f"（匹配是启发式的，请人工确认）：" + "、".join(phantom[:6]))
        res.metrics.append(Metric(f"{f_rel.split('/')[-1]} 路径", f"{len(doc_paths)} 条",
                                  f"{len(phantom)} 条对不上" if phantom else "都能对上注册",
                                  "warnv" if phantom else "good"))

    # --- 文档里写死的数字与现实对账 ---
    for spec in cfg.get("docs.claim", []) or []:
        did_anything = True
        f_rel, pattern, actual = spec.get("file"), spec.get("pattern"), spec.get("actual", "")
        p = cfg.root / (f_rel or "")
        if not (f_rel and pattern and p.exists()):
            res.add("警告", "adone.toml", f"docs.claim 配置不完整或文件不存在：{f_rel}")
            continue
        m = re.search(pattern, read_source(p))
        if not m:
            continue
        got = _actual_value(cfg, actual)
        if got is None:
            res.add("警告", f_rel, f"docs.claim 的 actual 表达式看不懂：{actual}")
            continue
        claimed = float(m.group(1))
        if abs(claimed - got) > float(spec.get("tolerance", 0.5)):
            res.add("警告", f_rel,
                    f"文里写「{m.group(1)}」，实际是 {got:g}（{actual}）")

    # --- 开发期物料：钩子与在途契约 ---
    hooks = cfg.get("docs.hooks_file")
    if hooks:
        did_anything = True
        hp = cfg.root / hooks
        if not hp.exists():
            res.add("警告", hooks, "没有钩子配置，完成门禁缺少强制点")
        hook_dir = hp.parent / "hooks"
        if hook_dir.is_dir():
            for h in sorted(hook_dir.iterdir()):
                if h.is_file() and not (h.stat().st_mode & 0o111):
                    res.add("警告", str(h.relative_to(cfg.root)), "钩子脚本没有可执行位")
    n_contract = len(list(cfg.acceptance_dir.glob("*.toml"))) \
        if cfg.acceptance_dir.is_dir() else 0
    res.metrics.append(Metric("开发期物料", f"{n_contract} 份契约",
                              "钩子已就位" if hooks and (cfg.root / hooks).exists()
                              else "没有钩子",
                              "good" if hooks and (cfg.root / hooks).exists() else "warnv"))

    # --- 技能索引与实际目录对不对得上 ---
    idx_md = cfg.skills_dir / "README.md"
    if idx_md.exists():
        did_anything = True
        txt = read_source(idx_md)
        for d in sorted(cfg.skills_dir.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists() and d.name not in txt:
                res.add("警告", str(idx_md.relative_to(cfg.root)), f"索引里没有 {d.name}")

    if not did_anything:
        return res.skip("没配任何 docs.* 检查项：这个维度不知道该看什么")

    res.notes.append("区分两类一致性：两份都自称权威的，必须完全一致（在代码质量维度判）；"
                     "文档自述是选摘的，只查「写了但代码里没有」的幻影，不要求全覆盖。")
    return res


def _actual_value(cfg, expr: str) -> float | None:
    """支持 count:<抽取器>:<路径> 与 receipt:coverage 两种取值。"""
    if expr.startswith("count:"):
        _, kind, rel = expr.split(":", 2)
        got = extract(kind, cfg.root / rel)
        return float(len(got)) if got is not None else None
    if expr == "receipt:coverage":
        from ..gate import load_latest
        r = load_latest(cfg) or {}
        v = (r.get("coverage") or {}).get("percent")
        return float(v) if v is not None else None
    return None
