"""完成门禁：真正执行检查，产出与代码状态绑死的回执。

「完成」的唯一口径是：存在一份回执，它的树哈希等于当前代码的树哈希，且其中每一步都通过。
Agent 贴的日志、勾的清单、说的话都不算数——回执由本模块写，哈希由本模块算。

诚实的边界：这套机制**提高伪造成本，不是密码学级不可伪造**。
能写文件的人理论上能伪造回执 JSON。缓解是回执内容含树哈希与命令输出，
任何人可以用 `adone gate check --explain` 独立复核。要做到真正不可伪造，
需要一个 Agent 无权写入的执行者（CI）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config
from .model import Step, TestResult


# --------------------------------------------------------------------------- 树哈希

def tree_files(cfg: Config) -> list[Path]:
    roots = cfg.get("gate.watch_roots", []) or []
    exts = {e if e.startswith(".") else f".{e}"
            for e in (cfg.get("gate.watch_exts", []) or [])}
    out: list[Path] = []
    for r in roots:
        base = cfg.root / r
        if not base.is_dir():
            continue
        out.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in exts)
    return sorted(out)


class GateError(Exception):
    pass


def tree_hash(cfg: Config) -> tuple[str, int]:
    """返回 (哈希, 文件数)。文件数过少直接报错——空哈希会让门禁恒等通过。"""
    files = tree_files(cfg)
    floor = int(cfg.get("gate.min_tree_files", 1) or 1)
    if len(files) < floor:
        raise GateError(
            f"只扫描到 {len(files)} 个受监视文件（下限 {floor}）。"
            f"这通常意味着 gate.watch_roots / watch_exts 配错了；"
            f"此时算出的哈希会恒等，门禁将形同虚设。")
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(cfg.root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest(), len(files)


# --------------------------------------------------------------------------- 执行

def run_step(cfg: Config, spec: dict) -> Step:
    argv = [a.replace("{cover_out}", str(cfg.cover_out)).replace("{root}", str(cfg.root))
            for a in spec["argv"]]
    st = Step(name=spec.get("name") or argv[0], cwd=spec.get("cwd", "."), argv=argv)
    t0 = time.time()
    try:
        proc = subprocess.run(argv, cwd=cfg.root / st.cwd, capture_output=True, text=True)
    except FileNotFoundError as e:
        st.seconds = round(time.time() - t0, 2)
        st.exit_code = 127
        st.ok = False
        st.note = f"命令不存在：{e.filename}"
        st.output_tail = st.note
        return st
    st.seconds = round(time.time() - t0, 2)
    st.exit_code = proc.returncode
    st.stdout = proc.stdout + proc.stderr
    st.output_tail = "\n".join(st.stdout.splitlines()[-25:])
    st.ok = proc.returncode == 0
    return st


def judge_step(cfg: Config, spec: dict, st: Step) -> TestResult | None:
    """按 kind 做额外判定。光看退出码会漏掉两类最常见的假绿。"""
    kind = spec.get("kind", "")

    if kind == "fmt":
        # 格式化检查工具往往永远退出 0，未格式化的文件名走 stdout
        bad = [ln for ln in st.stdout.splitlines() if ln.strip()]
        st.ok = st.exit_code == 0 and not bad
        if bad:
            st.note = f"{len(bad)} 个文件未格式化"
        return None

    if kind != "test":
        return None

    from .adapters import get
    ad = get(spec.get("adapter") or "", cfg.root)
    res = ad.parse_test_output(st.stdout)
    if res is None or not res.parsed:
        st.ok = False
        st.note = ("解析不出测试结果——要么适配器不认这种输出格式，"
                   "要么测试根本没跑起来。这种「通过」不能作为证据")
        return res

    for mark in spec.get("invalid_marks", []) or []:
        if mark in st.stdout:
            st.ok = False
            st.note = (f"输出里出现「{mark}」，说明有用例是被条件跳过的，"
                       f"这轮证据无效")
            return res
    if res.failed:
        st.ok = False
        st.note = f"{res.failed} 个用例失败"
    elif res.passed == 0:
        st.ok = False
        st.note = "没有任何用例真正跑过"
    else:
        st.note = (f"{res.passed} 通过 / {res.skipped} 跳过（顶层 {res.skip_top}）"
                   + (f" / 覆盖率 {res.coverage}%" if res.coverage is not None else ""))
    return res


def run_gate(cfg: Config, skip: list[str] | None = None) -> int:
    skip = skip or []
    problems = cfg.problems()
    if problems:
        print("配置有问题，门禁不跑（跑了也不算数）：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    specs = cfg.get("gate.step", []) or []
    print(f"跑门禁：{len(specs)} 步\n", flush=True)

    steps: list[Step] = []
    tests: TestResult | None = None
    test_step_name = cfg.get("coverage.source") or ""
    coverage: float | None = None
    skipped_any = False

    for spec in specs:
        name = spec.get("name", "?")
        if name in skip:
            print(f"  [跳过] {name}（本次回执会被标记为不完整）", flush=True)
            skipped_any = True
            continue
        st = run_step(cfg, spec)
        res = judge_step(cfg, spec, st)
        if res is not None and res.parsed:
            if tests is None or res.passed > tests.passed:
                tests = res
            if (not test_step_name or test_step_name == name) and res.coverage is not None:
                coverage = res.coverage
        steps.append(st)
        mark = "通过" if st.ok else "不通过"
        print(f"  [{mark}] {name}  {st.seconds}s" + (f"  {st.note}" if st.note else ""),
              flush=True)

    thr = cfg.get("coverage.threshold")
    if thr is not None:
        cov_step = Step(name="覆盖率", cwd=".", argv=["(读自测试步骤的输出)"])
        cov_step.exit_code = 0
        if coverage is None:
            cov_step.ok = False
            cov_step.note = "没解析到覆盖率数字"
        else:
            cov_step.ok = coverage >= float(thr)
            cov_step.note = f"{coverage}%（下限 {thr}%）"
        steps.append(cov_step)
        print(f"  [{'通过' if cov_step.ok else '不通过'}] 覆盖率  {cov_step.note}",
              flush=True)

    h, n = tree_hash(cfg)
    receipt = {
        "tool": "actuallydone",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "complete": not skipped_any,
        "seconds": round(time.time() - started, 1),
        "tree": {"hash": h, "file_count": n,
                 "roots": cfg.get("gate.watch_roots"),
                 "exts": sorted(cfg.get("gate.watch_exts"))},
        "tests": (tests or TestResult(parsed=False)).as_dict(),
        "coverage": {"percent": coverage, "threshold": thr},
        "steps": [s.as_receipt() for s in steps],
        "ok": bool(steps) and all(s.ok for s in steps),
    }
    path = cfg.receipts_dir / f"receipt-{receipt['id']}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(path, cfg.latest_receipt)
    cfg.dirty.unlink(missing_ok=True)
    prune_receipts(cfg)

    print(f"\n回执 {receipt['id']}：{'全绿' if receipt['ok'] else '未通过'}"
          f"（树 {n} 个文件 / {h[:12]}）")
    print(f"写入 {path.relative_to(cfg.root)}")
    if not receipt["ok"]:
        print("\n未通过的步骤：")
        for s in steps:
            if not s.ok:
                print(f"--- {s.name} ---\n{s.output_tail}\n")
    return 0 if receipt["ok"] else 1


def prune_receipts(cfg: Config) -> None:
    keep = int(cfg.get("gate.keep_receipts", 20) or 20)
    for p in sorted(cfg.receipts_dir.glob("receipt-*.json"), reverse=True)[keep:]:
        p.unlink(missing_ok=True)


# --------------------------------------------------------------------------- 校验

def load_latest(cfg: Config) -> dict | None:
    if not cfg.latest_receipt.exists():
        return None
    try:
        return json.loads(cfg.latest_receipt.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_dirty(cfg: Config) -> list[str]:
    if not cfg.dirty.exists():
        return []
    seen: list[str] = []
    for ln in cfg.dirty.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln and ln not in seen:
            seen.append(ln)
    return seen


def gate_problems(cfg: Config, receipt: dict | None, now_hash: str,
                  with_integrity: bool = True) -> tuple[list[str], list[str]]:
    """返回 (问题, 依据)。健康度维度与 check 共用这一套判定，避免两套口径。"""
    problems: list[str] = []
    details: list[str] = []

    if receipt is None:
        problems.append("没有任何回执：还没跑过 adone gate run")
        return problems, details

    details.append(f"回执 {receipt['id']}（{receipt['created_at']}）")
    if not receipt.get("ok"):
        bad = [s["name"] for s in receipt.get("steps", []) if not s.get("ok")]
        problems.append(f"回执本身未通过，失败步骤：{'、'.join(bad) or '未知'}")
    if not receipt.get("complete", True):
        problems.append("回执不完整（跑 run 时跳过了步骤），不能作为完成证据")

    old = receipt.get("tree", {}).get("hash")
    if old != now_hash:
        changed = read_dirty(cfg)
        hint = ("；钩子记录到的改动：" + "、".join(changed[:8])
                + ("…" if len(changed) > 8 else "")) if changed else ""
        problems.append(f"回执已过期：代码在跑完门禁之后又改过"
                        f"（回执 {str(old)[:12]} ≠ 当前 {now_hash[:12]}）{hint}")
    else:
        details.append(f"树哈希一致 {now_hash[:12]}"
                       f"（{receipt.get('tree', {}).get('file_count', '?')} 个文件）")
    return problems, details


def check_gate(cfg: Config, as_json: bool = False, explain: bool = False,
               with_integrity: bool = True) -> int:
    from .contracts import check_contracts, load_contracts
    from .integrity import integrity_problems

    receipt = load_latest(cfg)
    now_hash, now_files = tree_hash(cfg)
    problems, details = gate_problems(cfg, receipt, now_hash)
    if not problems and receipt is not None:
        cfg.dirty.unlink(missing_ok=True)  # 改了又改回来，清掉噪音标记

    contract_problems = check_contracts(cfg, receipt)
    problems.extend(contract_problems)
    contracts = load_contracts(cfg)
    if contracts and not contract_problems:
        n = sum(len(d.get("item") or []) for _, d in contracts)
        details.append(f"验收契约 {len(contracts)} 份 / {n} 条，全部绑定到已通过的用例")
    elif not contracts:
        details.append(f"没有验收契约文件（{cfg.acceptance_dir.relative_to(cfg.root)}/*.toml）")

    if with_integrity:
        problems.extend(integrity_problems(cfg, receipt))

    ok = not problems
    if as_json:
        print(json.dumps({
            "ok": ok, "problems": problems, "details": details,
            "receipt_id": receipt["id"] if receipt else None,
            "tree_hash": now_hash, "tree_files": now_files,
        }, ensure_ascii=False))
        return 0 if ok else 1

    if ok:
        print("门禁通过：可以宣称完成。")
    else:
        print("门禁未通过，以下问题必须先处理：")
        for p in problems:
            print(f"  - {p}")
    if explain or ok:
        for d in details:
            print(f"  · {d}")
    return 0 if ok else 1
