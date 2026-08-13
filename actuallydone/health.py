"""体检编排：挑维度、跑、算分、渲染。

默认只跑秒级的静态项并读最新门禁回执，不重跑测试——重活要显式要。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .dimensions import DIM_BY_KEY, DIMENSIONS, Dimension
from .model import DimResult
from .report import render


@dataclass
class Ctx:
    cfg: Config
    run_gate: bool = False
    with_probes: bool = False


def select(args) -> tuple[list[Dimension], dict[str, str]]:
    skipped: dict[str, str] = {}
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = want - set(DIM_BY_KEY)
        if unknown:
            print(f"未知维度：{'、'.join(sorted(unknown))}；可用：{'、'.join(DIM_BY_KEY)}",
                  file=sys.stderr)
            raise SystemExit(2)
        for d in DIMENSIONS:
            if d.key not in want:
                skipped[d.key] = "本轮用 --only 排除"
        return [d for d in DIMENSIONS if d.key in want], skipped

    chosen = []
    for d in DIMENSIONS:
        if not d.in_default and not args.with_probes:
            skipped[d.key] = f"默认不跑（{d.cost}），加 --with-probes 开启"
            continue
        chosen.append(d)
    if args.skip:
        drop = {s.strip() for s in args.skip.split(",") if s.strip()}
        chosen = [d for d in chosen if d.key not in drop]
        for k in drop:
            if k in DIM_BY_KEY:
                skipped[k] = "本轮用 --skip 排除"
    return chosen, skipped


def cmd_health(cfg: Config, args) -> int:
    if args.list:
        print("维度            权重  成本")
        for d in DIMENSIONS:
            print(f"{' ' if d.in_default else '*'}{d.key:<14}{d.weight:<5} {d.cost}")
        print("\n* 默认不跑，需要显式开启")
        return 0

    weights = cfg.get("score.weights", {}) or {}
    for d in DIMENSIONS:
        if d.key in weights:
            d.weight = float(weights[d.key])

    chosen, skipped = select(args)
    ctx = Ctx(cfg=cfg, run_gate=args.all, with_probes=args.with_probes)
    results: list[DimResult] = []

    def say(msg: str = "") -> None:
        """--json 时 stdout 只留 JSON，进度走 stderr，否则管道里没法直接解析。"""
        print(msg, file=sys.stderr if args.json else sys.stdout)

    say(f"体检 {cfg.name}：{'、'.join(d.key for d in chosen)}\n")
    for d in chosen:
        t0 = time.time()
        try:
            r = d.fn(ctx)
        except Exception as e:  # 单个维度炸了不该拖垮整份报告
            r = DimResult(d.key, d.title)
            r.add("错误", d.key, f"这个维度跑挂了：{type(e).__name__}: {e}")
        r.seconds = round(time.time() - t0, 2)
        r.title = d.title
        results.append(r)
        state = f"[{r.score:3d}]" if r.ran else "[ － ]"
        detail = (f"{r.errors} 错误 / {r.warnings} 警告  {r.seconds}s" if r.ran
                  else r.why_skipped)
        say(f"  {state} {d.title:<12} {detail}")

    for key, why in skipped.items():
        results.append(DimResult(key, DIM_BY_KEY[key].title, ran=False, why_skipped=why))
    order = [d.key for d in DIMENSIONS]
    results.sort(key=lambda r: order.index(r.key))

    ran = [r for r in results if r.ran]
    wsum = sum(DIM_BY_KEY[r.key].weight for r in ran)
    total = round(sum(r.score * DIM_BY_KEY[r.key].weight for r in ran) / wsum) if wsum else 0

    out = Path(args.out).resolve() if args.out else cfg.report
    out.parent.mkdir(parents=True, exist_ok=True)
    # 「总分 91」这种数字自带可信度暗示，把它是怎么来的写在同一屏里
    from .gate import evidence_line, load_latest
    render(results, out, total, [r.key for r in ran], DIMENSIONS, cfg.name,
           evidence_line(load_latest(cfg)))

    n_err = sum(r.errors for r in ran)
    n_warn = sum(r.warnings for r in ran)
    say(f"\n总分 {total}（{len(ran)}/{len(DIMENSIONS)} 个维度）："
        f"{n_err} 错误 / {n_warn} 警告")
    say(f"报告已写入 {out}")

    if args.json:
        print(json.dumps({
            "project": cfg.name,
            "total": total,
            "ran": [r.key for r in ran],
            "errors": n_err,
            "warnings": n_warn,
            "dimensions": [{
                "key": r.key, "title": r.title, "ran": r.ran,
                "why_skipped": r.why_skipped,
                "score": r.score if r.ran else None,
                "errors": r.errors, "warnings": r.warnings, "seconds": r.seconds,
                "findings": [vars(f) for f in r.findings],
                "metrics": [vars(m) for m in r.metrics],
            } for r in results],
        }, ensure_ascii=False, indent=2))

    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([opener, str(out)], check=False)
    return 1 if n_err else 0
