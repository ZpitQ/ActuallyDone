"""完成门禁：真正执行检查，产出与代码状态绑死的回执。

「完成」的唯一口径是：存在一份回执，它的树哈希等于当前代码的树哈希，且其中每一步都通过。
Agent 贴的日志、勾的清单、说的话都不算数——回执由本模块写，哈希由本模块算。

回执还带自哈希与指向上一份的 `prev`，链头在 `.adone/chain.json`：手写一份全绿回执
从此要重算自哈希、改链头、让 prev 追得到，而链头变动在 git diff 里显眼。

诚实的边界：这套机制**提高伪造成本，不是密码学级不可伪造**。
能写文件的人理论上能重算整条链。缓解是回执内容含树哈希与命令输出，
任何人可以用 `adone gate check --explain` 独立复核、`--spotcheck` 当场抽跑。
要做到真正不可伪造，需要一个 Agent 无权写入的执行者（CI）。
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
    st.started_at = t0
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
    res = ad.parse_test_run(st.stdout, cwd=cfg.root / st.cwd,
                            since=st.started_at or None)
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


def execute_steps(cfg: Config, skip: list[str] | None = None) -> dict:
    """真跑配置里的每一步，返回原始结果，不落任何盘。

    `gate run` 与 `audit --rerun` 共用它：复核者要能跑出自己的一份结果，
    又不能顺手覆盖实现者的回执——那等于把被审的证据抹掉。
    """
    skip = skip or []
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

    return {"steps": steps, "tests": tests, "coverage": coverage, "threshold": thr,
            "complete": not skipped_any, "seconds": round(time.time() - started, 1)}


def run_gate(cfg: Config, skip: list[str] | None = None) -> int:
    problems = cfg.problems()
    if problems:
        print("配置有问题，门禁不跑（跑了也不算数）：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.receipts_dir.mkdir(parents=True, exist_ok=True)
    ran = execute_steps(cfg, skip)
    steps = ran["steps"]
    tests, coverage, thr = ran["tests"], ran["coverage"], ran["threshold"]

    from .policy import ensure_baseline, snapshot, snapshot_hash

    h, n = tree_hash(cfg)
    said = ensure_baseline(cfg, load_latest(cfg))
    if said:
        print(f"\n{said}")
    pol = _policy_baseline_or_none(cfg)
    prev = chain_head(cfg)
    receipt = {
        "tool": "actuallydone",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "complete": ran["complete"],
        "seconds": ran["seconds"],
        "tree": {"hash": h, "file_count": n,
                 "roots": cfg.get("gate.watch_roots"),
                 "exts": sorted(cfg.get("gate.watch_exts"))},
        "policy": {"hash": snapshot_hash(snapshot(cfg)),
                   "baseline_hash": (pol or {}).get("hash"),
                   "baseline_reason": (pol or {}).get("reason")},
        "tests": (tests or TestResult(parsed=False)).as_dict(),
        "coverage": {"percent": coverage, "threshold": thr},
        "steps": [s.as_receipt() for s in steps],
        "ok": bool(steps) and all(s.ok for s in steps),
        "seq": prev.get("seq", 0) + 1,
        "prev": prev.get("head"),
    }
    receipt["evidence"] = evidence_of(cfg, receipt)
    receipt["self_hash"] = self_hash(receipt)
    path = cfg.receipts_dir / f"receipt-{receipt['id']}.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(path, cfg.latest_receipt)
    write_chain_head(cfg, receipt)
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


# --------------------------------------------------------------------------- 证据链

def self_hash(receipt: dict) -> str:
    """回执对自己内容的哈希（不含该字段本身）。

    手写一份回执从此不再是「填一个树哈希」：还得把这个数算对、把链头改掉、
    让 prev 对得上。挡不住铁了心重算整条链的人，但那已经不是顺手绕过了。
    """
    body = {k: v for k, v in receipt.items() if k != "self_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def chain_head(cfg: Config) -> dict:
    if not cfg.chain.exists():
        return {}
    try:
        data = json.loads(cfg.chain.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_chain_head(cfg: Config, receipt: dict) -> None:
    cfg.chain.write_text(json.dumps({
        "head": receipt["self_hash"],
        "seq": receipt["seq"],
        "receipt_id": receipt["id"],
        "updated_at": receipt["created_at"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def chain_problems(cfg: Config, receipt: dict | None) -> tuple[list[str], list[str]]:
    """校验最新回执与链头。返回（问题，依据）。

    升级前写的回执没有这些字段，按「早于链机制」处理并给一句提示——
    否则所有已装项目一升级就全红，那只会让人把这套检查关掉。
    """
    if receipt is None:
        return [], []
    if "self_hash" not in receipt:
        head = chain_head(cfg)
        if head:
            # 链已经建起来了还冒出一份链外回执：不是升级遗留，是有人把 latest.json 换了
            return ([f"这份回执不在证据链上，而本仓库的链头已经指到回执 "
                     f"{head.get('receipt_id')}（第 {head.get('seq')} 环）："
                     f"latest.json 被换成了一份更老的回执"], [])
        return [], ["这份回执早于证据链机制（重跑一次 adone gate run 即可纳入链）"]

    problems: list[str] = []
    if self_hash(receipt) != receipt["self_hash"]:
        problems.append("回执的自哈希对不上：内容被改过（或被手写过），它不能作为证据")
        return problems, []

    head = chain_head(cfg)
    if not head:
        problems.append("证据链头（chain.json）不见了：无法确认这份回执是不是最新的那一份")
    elif head.get("head") != receipt["self_hash"]:
        problems.append(f"回执与证据链头对不上（链头指向回执 {head.get('receipt_id')}）："
                        f"latest.json 被换过")
    prev = receipt.get("prev")
    if prev:
        older = _find_receipt_by_hash(cfg, prev)
        if older is None and _receipts_on_disk(cfg) >= int(cfg.get("gate.keep_receipts", 20) or 20):
            pass   # 老回执被 prune 掉了，正常
        elif older is None:
            problems.append(f"上一份回执（自哈希 {str(prev)[:12]}）在 receipts/ 里找不到："
                            f"证据链断了，中间那份被删或被改过")
    details = [f"证据链第 {receipt.get('seq', '?')} 环，自哈希 {receipt['self_hash'][:12]}"]
    return problems, details


def _receipts_on_disk(cfg: Config) -> int:
    return len(list(cfg.receipts_dir.glob("receipt-*.json")))


def _find_receipt_by_hash(cfg: Config, want: str) -> dict | None:
    for p in sorted(cfg.receipts_dir.glob("receipt-*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("self_hash") == want:
            return data
    return None


def evidence_of(cfg: Config, receipt: dict) -> dict:
    """这份回执的证据强度。

    先只有「自述」一档：本地跑出来的东西，再怎么自洽也只是自述。
    字段结构给以后的 git 绑定与 CI 签名留好位置——「总分 91」这种数字
    自带可信度标签，比在脚注里写一句免责声明管用。
    """
    return {
        "level": "self-reported",
        "policy_locked": _policy_baseline_or_none(cfg) is not None,
        "chained": True,
    }


def _policy_baseline_or_none(cfg: Config) -> dict | None:
    """基线坏了在这里按「没锁」算：真正把它报出来的是 check，不必两处都喊。"""
    from .policy import BaselineBroken, load_baseline
    try:
        return load_baseline(cfg)
    except BaselineBroken:
        return None


def evidence_line(receipt: dict | None) -> str:
    if not receipt:
        return ""
    ev = receipt.get("evidence") or {}
    if not ev:
        return "证据强度：自述（本地跑）· 这份回执早于证据链机制"
    bits = ["自述（本地跑）" if ev.get("level") == "self-reported" else str(ev.get("level")),
            "判据已锁" if ev.get("policy_locked") else "判据未锁",
            "回执链完整" if ev.get("chained") else "不在证据链上"]
    return "证据强度：" + " · ".join(bits)


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


def collect_check(cfg: Config, with_integrity: bool = True,
                  spotcheck: int = 0) -> dict:
    """把一次复核的全部判定收成数据，不打印。

    `check` 与 `audit` 共用这一份判定：两条命令口径分家，等于给「换个命令再问一次」
    留了一条后门。
    """
    from .contracts import check_contracts, load_contracts
    from .integrity import integrity_problems
    from .policy import policy_problems

    receipt = load_latest(cfg)
    try:
        now_hash, now_files = tree_hash(cfg)
    except GateError as e:
        # 算不出树哈希本身就是结论（多半是有人把 watch_roots 缩没了），
        # 但不能就此崩掉：判据锁与证据链的结论此时恰恰是最该看见的
        now_hash, now_files = "", 0
        problems, details = [str(e)], []
    else:
        problems, details = gate_problems(cfg, receipt, now_hash)
        if not problems and receipt is not None:
            cfg.dirty.unlink(missing_ok=True)  # 改了又改回来，清掉噪音标记

    chain_bad, chain_detail = chain_problems(cfg, receipt)
    problems.extend(chain_bad)
    details.extend(chain_detail)

    policy_bad, policy_detail = policy_problems(cfg, receipt)
    problems.extend(policy_bad)
    details.extend(policy_detail)

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

    spotchecked: list[str] = []
    if spotcheck and receipt is not None:
        from .spotcheck import spot_check
        sc_problems, sc_details = spot_check(cfg, receipt, spotcheck)
        problems.extend(sc_problems)
        details.extend(sc_details)
        spotchecked = sc_details

    return {
        "ok": not problems, "problems": problems, "details": details,
        "receipt_id": receipt["id"] if receipt else None,
        "receipt": receipt,
        "tree_hash": now_hash, "tree_files": now_files,
        "evidence": (receipt or {}).get("evidence") or {},
        "evidence_line": evidence_line(receipt),
        "spotcheck": spotchecked,
    }


def check_gate(cfg: Config, as_json: bool = False, explain: bool = False,
               with_integrity: bool = True, spotcheck: int = 0) -> int:
    got = collect_check(cfg, with_integrity=with_integrity, spotcheck=spotcheck)
    ok, problems, details = got["ok"], got["problems"], got["details"]
    line = got["evidence_line"]
    if as_json:
        print(json.dumps({
            "ok": ok, "problems": problems, "details": details,
            "receipt_id": got["receipt_id"],
            "tree_hash": got["tree_hash"], "tree_files": got["tree_files"],
            "evidence": got["evidence"],
            "evidence_line": line,
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
    if line and (explain or ok):
        print(line)
    return 0 if ok else 1
