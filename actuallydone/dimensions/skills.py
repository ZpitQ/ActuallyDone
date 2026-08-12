"""维度：技能沉淀。"""

from __future__ import annotations

import re

from ..model import DimResult, Metric
from ..skills_scan import est_tokens, scan_skills


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("skills", "技能沉淀")
    if not cfg.skills_dir.is_dir():
        return res.skip(f"技能目录不存在（{cfg.get('project.skills_dir')}），"
                        f"跑 adone install 装一套")

    agent_doc = cfg.get("skills.agent_doc")
    inv_pattern = cfg.get("skills.invariant_pattern", "")
    reports = scan_skills(cfg.skills_dir, cfg.root,
                          cfg.root / agent_doc if agent_doc else None, inv_pattern)
    if not reports:
        return res.skip("技能目录里没有任何带 SKILL.md 的技能")

    for r in reports:
        for i in r.issues:
            res.add(i.severity, f"{r.name} · {i.where}", i.message)

    avg = round(sum(r.score for r in reports) / len(reports))
    desc_tokens = sum(est_tokens(r.front.get("description", "")) for r in reports)
    body_tokens = sum(r.skill_tokens for r in reports)
    bad_refs = sum(len(r.code_refs_bad) for r in reports)
    ok_refs = sum(r.code_refs_ok for r in reports)

    res.metrics = [
        Metric("技能数", str(len(reports)),
               f"{sum(1 for r in reports if r.auto_invoke)} 个自动触发"),
        Metric("平均健康分", str(avg), "错误 -15，警告 -5",
               "good" if avg >= 85 else "warnv"),
        Metric("代码引用", f"{ok_refs} 有效",
               f"{bad_refs} 条失效" if bad_refs else "无失效引用",
               "bad" if bad_refs else "good"),
        Metric("常驻 token", str(desc_tokens),
               f"正文另有 {body_tokens}，仅触发后加载"),
    ]

    expected = cfg.get("skills.invariants", []) or []
    if inv_pattern and expected:
        covered = set().union(*(r.invariants for r in reports)) if reports else set()
        missing = [i for i in expected if i not in covered]
        res.metrics.append(Metric(
            "不变量覆盖", f"{len(expected) - len(missing)}/{len(expected)}",
            "未提及：" + (", ".join(missing) if missing else "无")))

    res.notes.append("「代码引用失效」是技能腐坏的主要形态——代码改了而技能里的路径行号没跟着改。")
    res.notes.append("触发准确率无法静态检测，只能人工抽样：随机挑几次会话，看该触发的技能有没有触发。")
    return res
