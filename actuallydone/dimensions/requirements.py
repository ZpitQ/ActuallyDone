"""维度：需求台账。"""

from __future__ import annotations

from ..ledger import VALID_STATUS, build_anchor_index, load_ledger, verify_anchor
from ..model import DimResult, Metric


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("requirements", "需求台账")
    files = load_ledger(cfg)
    if not files:
        return res.skip(
            f"还没有需求台账（{cfg.requirements_dir.relative_to(cfg.root)}/*.toml），"
            f"跑 adone requirements init 生成骨架")

    idx = build_anchor_index(cfg)
    total = done = partial = todo = dropped = 0
    lost = noevidence = 0

    for path, data in files:
        rel = path.relative_to(cfg.root)
        if "__error__" in data:
            res.add("错误", str(rel), f"台账解析失败：{data['__error__']}")
            continue
        for item in data.get("item", []):
            total += 1
            rid = item.get("id", "?")
            text = item.get("需求") or item.get("requirement") or ""
            status = (item.get("状态") or item.get("status") or "todo").strip()
            if status not in VALID_STATUS:
                res.add("警告", f"{rel} {rid}",
                        f"状态「{status}」不是 {'/'.join(VALID_STATUS)} 之一")
                status = "todo"
            done += status == "done"
            partial += status == "partial"
            dropped += status == "dropped"
            todo += status == "todo"

            anchors = item.get("证据") or item.get("evidence") or []
            if status in ("done", "partial"):
                if not anchors:
                    noevidence += 1
                    res.add("警告", rid, f"标了 {status} 却没有任何证据锚点：{text[:40]}")
                for a in anchors:
                    sev, msg = verify_anchor(cfg, a, idx)
                    if sev:
                        lost += sev == "错误"
                        res.add(sev, rid, f"{msg}（{text[:30]}）")

    effective = total - dropped
    coverage = round((done + 0.5 * partial) / effective * 100, 1) if effective else 0.0
    if total and todo / total > 0.8:
        res.add("提示", "台账成熟度",
                f"{todo}/{total} 条还是生成骨架时的 todo 初值，"
                f"覆盖率在人工校对状态之前不代表真实进度")

    res.metrics = [
        Metric("需求覆盖率", f"{coverage}%",
               f"done {done} + partial {partial} / 有效 {effective} 条",
               "good" if coverage >= 70 else "warnv" if coverage >= 40 else "bad"),
        Metric("台账条目", str(total),
               f"{len(files)} 份台账，其中 dropped {dropped} 条不计入"),
        Metric("失联需求", str(lost), "标了已做，但证据锚点已失效",
               "good" if not lost else "bad"),
        Metric("无证据条目", str(noevidence), "标了已做却没写锚点",
               "good" if not noevidence else "warnv"),
        Metric("待办", str(todo), "尚未实现的条目"),
    ]
    res.notes.append("覆盖率是进度指标，低不扣分——没做的需求不等于项目不健康。"
                     "真正的偏离是「失联需求」：曾经声称做过，如今证据没了。")
    return res
