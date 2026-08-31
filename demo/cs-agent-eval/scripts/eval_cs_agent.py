#!/usr/bin/env python3
"""读 adone/eval/*.toml，跑内存客服，按行打印 PASS/FAIL。失败时退出码非 0。"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cs_agent import run  # noqa: E402


def _scenarios(eval_dir: Path) -> list[dict]:
    out: list[dict] = []
    if not eval_dir.is_dir():
        return out
    for p in sorted(eval_dir.glob("*.toml")):
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        rows = data.get("scenario")
        items = rows if isinstance(rows, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or p.stem).strip()
            out.append({**item, "id": sid})
    return out


def _ok(sc: dict, result: dict) -> tuple[bool, str]:
    kind = sc.get("kind") or "recall"
    if kind == "recall":
        hits = result["hits"]
        for name in sc.get("must") or []:
            if name not in hits:
                return False, f"未召回 {name}"
        for name in sc.get("must_not") or []:
            if name in hits:
                return False, f"误召回 {name}"
        return True, ""
    if kind == "merge":
        expect = sc.get("expect")
        if result["merged"] != expect:
            return False, f"合并得 {result['merged']!r}，期望 {expect!r}"
        return True, ""
    if kind == "hitl":
        want = bool(sc.get("expect_interrupt"))
        if result["interrupt"] != want:
            return False, f"打断={result['interrupt']}，期望 {want}"
        return True, ""
    return False, f"未知 kind {kind}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑这一条场景 id")
    args = ap.parse_args()
    scenes = _scenarios(ROOT / "adone" / "eval")
    if args.only:
        scenes = [s for s in scenes if s["id"] == args.only]
        if not scenes:
            print(f"FAIL {args.only}  名单里没有这条", flush=True)
            return 1
    failed = 0
    for sc in scenes:
        result = run(ROOT, str(sc.get("query") or ""), sc.get("amount"))
        passed, why = _ok(sc, result)
        line = f"{'PASS' if passed else 'FAIL'} {sc['id']}"
        if why:
            line += f"  {why}"
        print(line, flush=True)
        if not passed:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
