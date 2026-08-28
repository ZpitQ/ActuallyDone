"""抽查真跑：从回执声称通过的用例里随机抽几条，当场再跑一遍。

回执里的「通过」终究是解析出来的文本。文本可以来自一个假脚本，也可以来自
一次早已过时的运行。抽查把这件事变成实证：抽中的用例现在就跑，跑不过就不算完成。

默认关闭。钩子每次收工都会跑 check，几秒的代价不该压在那条路径上；
交付前与 CI 里显式开 `--spotcheck`。
"""

from __future__ import annotations

import random
import subprocess
import time

from .config import Config
from .gate import launch_argv, resolve_cmd

TIMEOUT = 600


def _test_step(cfg: Config) -> dict | None:
    for s in cfg.get("gate.step", []) or []:
        if s.get("kind") == "test":
            return s
    return None


def _candidates(cfg: Config, receipt: dict) -> tuple[list[str], str]:
    """优先抽契约绑定的用例——那些是需求真正落在的地方。"""
    from .contracts import load_contracts
    bound: list[str] = []
    for _, data in load_contracts(cfg):
        for item in data.get("item") or []:
            if item.get("test"):
                bound.append(str(item["test"]))
    if bound:
        return sorted(set(bound)), "契约绑定用例"
    names = (receipt.get("tests") or {}).get("passed_names") or []
    return sorted({str(n) for n in names}), "回执通过名单"


def spot_check(cfg: Config, receipt: dict, n: int) -> tuple[list[str], list[str]]:
    """返回（问题，依据）。做不到的一律说「未评估」，不说「通过」。"""
    from .adapters import get

    step = _test_step(cfg)
    if step is None:
        return [], ["抽查未评估：没有 kind=test 的门禁步骤，不知道该怎么跑单条用例"]

    ad = get(step.get("adapter") or cfg.get("tests.adapter") or "", cfg.root)
    names, source = _candidates(cfg, receipt)
    if not names:
        return [], [f"抽查未评估：{source}里没有用例名（测试步骤可能没开 -v）"]

    picked = random.sample(names, min(max(int(n), 1), len(names)))
    argvs = [(name, ad.single_test_argv(name)) for name in picked]
    if all(a is None for _, a in argvs):
        return [], [f"抽查未评估：{ad.name} 适配器不会只跑一条用例"]

    cwd = cfg.root / (step.get("cwd") or ".")
    problems: list[str] = []
    ran: list[str] = []
    for name, argv in argvs:
        if argv is None:
            continue
        exe = resolve_cmd(argv[0], cwd)
        if exe is None:
            problems.append(f"抽查用例 {name} 跑不起来：命令 {argv[0]} 在 PATH 与 "
                            f"{step.get('cwd') or '.'} 下都没找到")
            continue
        t0 = time.time()
        try:
            proc = subprocess.run(launch_argv(exe, argv[1:]), cwd=cwd,
                                  capture_output=True, text=True, errors="replace",
                                  timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append(f"抽查用例 {name} 跑不起来（{' '.join(argv)}）：{e}")
            continue
        out = proc.stdout + proc.stderr
        res = ad.parse_test_run(out, cwd=cwd, since=t0)
        top = name.split("/")[0]
        # 退出码 0 还不够：-run 打错字会「一条没跑」也返回 0，那不是通过，是没跑
        hit = bool(res and res.parsed and top in {p.split("/")[0] for p in res.passed_names})
        if proc.returncode != 0 or (res and res.failed):
            tail = "\n".join(out.splitlines()[-12:])
            problems.append(f"抽查用例 {name} 现在跑不过——回执里它是通过的："
                            f"\n      {tail}")
        elif not hit:
            problems.append(f"抽查用例 {name} 这次一条都没跑起来"
                            f"（{' '.join(argv)} 没有产出它的通过记录）："
                            f"回执里的通过记录可能不是它跑出来的")
        else:
            ran.append(name)

    details = []
    if ran:
        details.append(f"抽查真跑 {len(ran)} 条（取自{source}）：{'、'.join(ran)} 现在仍然通过")
    skipped = [nm for nm, a in argvs if a is None]
    if skipped:
        details.append(f"抽查未评估 {len(skipped)} 条（适配器不支持单跑）：{'、'.join(skipped)}")
    return problems, details
