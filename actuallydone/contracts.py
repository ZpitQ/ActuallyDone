"""验收契约：把每条需求钉到一个用例名上，由脚本去核。

自然语言的验收标准挡不住两件事：需求缩水（做了三条里的两条就说完成）
和编用例名（清单勾了，但那个用例根本不存在）。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .config import Config
from .textio import read as read_source


def load_contracts(cfg: Config) -> list[tuple[Path, dict]]:
    """读 <material_dir>/acceptance/*.toml（不含子目录，done/ 归档不再校验）。"""
    d = cfg.acceptance_dir
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.toml")):
        try:
            out.append((p, tomllib.loads(p.read_text(encoding="utf-8"))))
        except Exception as e:  # 契约本身写坏了也算不通过
            out.append((p, {"__error__": str(e)}))
    return out


def known_test_names(cfg: Config) -> set[str] | None:
    from .adapters import get
    ad = get(cfg.get("tests.adapter") or "", cfg.root)
    roots = [cfg.root / r for r in (cfg.get("tests.roots", []) or [])]
    return ad.test_names(roots)


def known_scenario_names(cfg: Config) -> set[str] | None:
    """第一个 adapter=eval 的步骤能列出的场景名。没有该步骤则无法核验。"""
    from .adapters import first_eval_step, get
    if first_eval_step(cfg) is None:
        return None
    ad = get("eval", cfg.root)
    roots = [cfg.root / r for r in (cfg.get("tests.roots", []) or [])]
    return ad.test_names(roots)


def _has_test_binding(contracts: list[tuple[Path, dict]]) -> bool:
    for _, data in contracts:
        if "__error__" in data:
            continue
        for item in data.get("item") or []:
            if item.get("test"):
                return True
    return False


def check_contracts(cfg: Config, receipt: dict | None) -> list[str]:
    """返回问题列表，空列表表示契约全绿。"""
    problems: list[str] = []
    contracts = load_contracts(cfg)
    if not contracts:
        return problems

    known = known_test_names(cfg)
    if _has_test_binding(contracts) and known is None:
        return [f"有 {len(contracts)} 份验收契约，但配置的测试适配器"
                f"（tests.adapter={cfg.get('tests.adapter') or '空'}）列不出用例名，"
                f"无法核验。先把 tests.adapter / tests.roots 配对"]

    passed = set(receipt["tests"]["passed_names"]) if receipt else set()
    # 回执里的子用例名形如 TestX/子用例，顶层名要能匹配上
    passed_top = {n.split("/")[0] for n in passed}

    for path, data in contracts:
        rel = path.relative_to(cfg.root)
        if "__error__" in data:
            problems.append(f"{rel}: 契约文件解析失败（{data['__error__']}）")
            continue
        items = data.get("item") or []
        if not items:
            problems.append(f"{rel}: 契约里一条验收项都没有")
            continue
        for i, item in enumerate(items, 1):
            want = item.get("要求") or item.get("requirement") or f"第 {i} 条"
            test = item.get("test")
            scenario = item.get("scenario")
            impl = item.get("impl")
            prefix = f"{rel} 第 {i} 条「{want}」"
            if test:
                # 同时有 test 与 scenario 时以 test 为准，vibe 契约判定顺序不变
                if known is None or test not in known:
                    problems.append(
                        f"{prefix}：用例 {test} 在测试源码里根本不存在")
                    continue
                if receipt is None:
                    problems.append(f"{prefix}：没有回执可以证明 {test} 跑过")
                    continue
                if test not in passed_top:
                    problems.append(
                        f"{prefix}：用例 {test} 没有出现在回执的通过名单里")
                    continue
            elif scenario:
                scenarios = known_scenario_names(cfg)
                if scenarios is None:
                    problems.append(f"{prefix}：未配置 eval 步骤，scenario 无法核验")
                    continue
                if scenario not in scenarios:
                    problems.append(
                        f"{prefix}：场景 {scenario} 在 eval 名单里根本不存在")
                    continue
                if receipt is None:
                    problems.append(f"{prefix}：没有回执可以证明 {scenario} 跑过")
                    continue
                if scenario not in passed and scenario not in passed_top:
                    problems.append(
                        f"{prefix}：场景 {scenario} 没有出现在回执的通过名单里")
                    continue
            else:
                problems.append(f"{prefix}：没绑定用例名")
                continue
            if impl:
                problems.extend(check_impl_ref(cfg, prefix, impl))
    return problems


def check_impl_ref(cfg: Config, prefix: str, impl: str) -> list[str]:
    m = re.match(r"^(.+?)(?::(\d+))?$", impl.strip())
    if not m:
        return [f"{prefix}：impl 写法无法解析（{impl}）"]
    target = cfg.root / m.group(1)
    if not target.exists():
        return [f"{prefix}：impl 指向的文件不存在（{m.group(1)}）"]
    if m.group(2):
        total = len(read_source(target).splitlines())
        if int(m.group(2)) > total:
            return [f"{prefix}：impl 行号越界（{impl}，该文件只有 {total} 行）"]
    return []


def verify_only(cfg: Config) -> int:
    from .gate import load_latest
    problems = check_contracts(cfg, load_latest(cfg))
    if not problems:
        n = sum(len(d.get("item") or []) for _, d in load_contracts(cfg))
        print(f"验收契约全绿（{n} 条）" if n else "没有验收契约文件")
        return 0
    print("验收契约未通过：")
    for p in problems:
        print(f"  - {p}")
    return 1
