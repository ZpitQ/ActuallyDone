"""把技能与钩子模板渲染进项目。

技能必须落在 Agent 平台认的位置（Cursor 只认 `.cursor/skills/`），所以工具不能
「自带技能」，只能渲染。渲染时要替掉模板里的占位符——把「85% 是当前实测水位」
原样抄进别人的项目，就是在替他们说谎。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from .config import Config

TEMPLATES = Path(__file__).resolve().parent / "templates"

# 随包发布的通用技能（方法通用，内容可参数化）
GENERIC_SKILLS = ("completion-gate", "acceptance-contract", "test-integrity",
                  "verified-delivery")
# 只给骨架的项目专有技能：它们的价值恰恰在于内容是本项目踩出来的
PROJECT_SKILLS = ("coding-standards", "pr-review-checklist", "test-driven-dev")

# 各生态的措辞，用来把技能里的例子写成读者认识的样子
DIALECT = {
    "go": {
        "ASSERT_API": "t.Error / t.Fatal 系列",
        "SKIP_API": "t.Skip(...)",
        "TEST_FUNC_FORM": "顶层用例函数名（`func TestXxx`）",
        "TEST_NAME_EXAMPLE": "TestOrderRejectsNegativePrice",
        # 例子里的路径要一眼看出是占位符：写成真路径的话，技能自检会把它当成失效引用
        "IMPL_EXAMPLE": "<实现文件>.go:168",
        "FMT_CMD": "gofmt -l . 无输出",
        "BUILD_CMD": "go build ./... 通过",
    },
    "node": {
        "ASSERT_API": "expect(...) / assert(...)",
        "SKIP_API": "it.skip(...) / xit(...)",
        "TEST_FUNC_FORM": "用例标题（`it(\"...\")` 里的那个字符串）",
        "TEST_NAME_EXAMPLE": "拒绝负数价格的订单",
        "IMPL_EXAMPLE": "<实现文件>.ts:168",
        "FMT_CMD": "npm run lint 通过",
        "BUILD_CMD": "npm run build 通过",
    },
    "python": {
        "ASSERT_API": "assert / self.assertXxx",
        "SKIP_API": "@skip / pytest.mark.skip",
        "TEST_FUNC_FORM": "用例函数名（`def test_xxx`）",
        "TEST_NAME_EXAMPLE": "test_order_rejects_negative_price",
        "IMPL_EXAMPLE": "<实现文件>.py:168",
        "FMT_CMD": "ruff check . 通过",
        "BUILD_CMD": "python -m compileall -q . 通过",
    },
}
FALLBACK = {
    "ASSERT_API": "断言函数",
    "SKIP_API": "跳过标记",
    "TEST_FUNC_FORM": "用例名",
    "TEST_NAME_EXAMPLE": "TODO填用例名",
    "IMPL_EXAMPLE": "<实现文件>:168",
    "FMT_CMD": "TODO：格式检查命令",
    "BUILD_CMD": "TODO：构建命令",
}


def adone_entry(cfg: Config) -> str:
    """仓库内的免安装入口（相对仓库根）；工具是 pip 装的则返回空串。

    优先走仓库内入口：没装 pip 包时钩子不该哑掉——钩子静默失效，
    看起来和「门禁通过了」一模一样。
    """
    vendored = Path(__file__).resolve().parent.parent / "bin" / "adone"
    try:
        return vendored.relative_to(cfg.root).as_posix()
    except ValueError:
        return ""


def variables(cfg: Config) -> dict[str, str]:
    eco = next((e for e in cfg.ecosystems if e in DIALECT), "")
    v = dict(FALLBACK)
    v.update(DIALECT.get(eco, {}))

    entry = adone_entry(cfg)
    # 文档里写 python3 而不是 sys.executable：把 /opt/homebrew/opt/python@3.13/bin/python3.13
    # 抄进技能，换台机器就是错的
    cmd = f"python3 {entry}" if entry else "adone"
    thr = cfg.get("coverage.threshold")
    steps = [s.get("name", "?") for s in (cfg.get("gate.step") or [])]
    roots = cfg.get("gate.watch_roots") or []
    exts = cfg.get("gate.watch_exts") or []

    v.update({
        "PROJECT": cfg.name,
        "ADONE": cmd,
        "ADONE_ENTRY": json.dumps(entry, ensure_ascii=False),
        # 钩子是本机生成物，且它的 PATH 不可控（实测拿到过一个不带 ~/.local/bin 的环境），
        # 所以这里把安装时的绝对路径烧进去。技能文档里仍然只写 adone，不烧机器路径。
        "ADONE_CMD": json.dumps(shutil.which("adone") or "", ensure_ascii=False),
        "REPO_PATH": str(cfg.root),
        "STATE_DIR": cfg.get("project.state_dir"),
        "MATERIAL_DIR": cfg.get("project.material_dir"),
        "SKILLS_DIR": cfg.get("project.skills_dir"),
        "ACCEPTANCE_DIR": f"{cfg.get('project.material_dir')}/acceptance",
        "REQUIREMENTS_DIR": f"{cfg.get('project.material_dir')}/requirements",
        "RECEIPT_PATH": f"{cfg.get('project.state_dir')}/latest.json",
        "BASELINE_PATH": f"{cfg.get('project.state_dir')}/test-baseline.json",
        "WATCH_DESC": (f"{'、'.join(roots)} 下所有 {'/'.join(exts)}"
                       if roots else "受监视目录（见 adone.toml）"),
        "GATE_STEPS": "、".join(steps) or "见 adone.toml 的 gate.step",
        "WATCH_ROOTS": " ".join(f'"{r}"' for r in roots),
        "WATCH_EXTS": " ".join(f'"{e}"' for e in exts),
        # 没设阈值就别替人编一个数字
        "COVERAGE_CLAIM": f"、覆盖率不低于 {thr}%" if thr is not None else "",
        "COVERAGE_DESC": (f"下限 {thr}%，由 adone.toml 的 coverage.threshold 定"
                          if thr is not None else "本项目没设覆盖率下限"),
        "COVERAGE_ITEM": (f"\n- [ ] 覆盖率不低于 {thr}%" if thr is not None else ""),
        "THRESHOLD_NOTE": (f"当前下限 {thr}%——这个数字是实测水位，不是许愿。"
                           if thr is not None else "本项目还没设下限，设一个再谈这条。"),
        "HOOKS_NOTE": _hooks_note(cfg, cmd),
    })
    return v


def _hooks_note(cfg: Config, cmd: str) -> str:
    hooks = cfg.root / ".cursor" / "hooks.json"
    if hooks.exists():
        return (f"`.cursor/hooks.json` 里 `stop` 钩子会在你想收工时跑 `{cmd} gate check`，"
                f"不通过就把问题列表作为下一条用户消息推回来（`loop_limit` 为 3，最多推三次）。"
                f"它没有否决权——但你若无视它硬说完成，问题清单会白纸黑字留在会话里。")
    return (f"本项目还没装钩子。装上之后（`{cmd} install --with-hooks`），"
            f"Agent 想收工时会自动跑一次 `gate check`，不通过就把问题推回来。")


def render(text: str, v: dict[str, str]) -> str:
    def sub(m):
        key = m.group(1)
        if key not in v:
            raise KeyError(f"模板里有未知占位符 {{{{{key}}}}}")
        return v[key]
    return re.sub(r"\{\{(\w+)\}\}", sub, text)


def cmd_install(cfg: Config, args) -> int:
    v = variables(cfg)
    skills_root = Path(args.skills_dir).resolve() if args.skills_dir else cfg.skills_dir
    hooks_only = getattr(args, "hooks_only", False)
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    want = [] if hooks_only else [s for s in (*GENERIC_SKILLS, *PROJECT_SKILLS)
                                  if only is None or s in only]
    if only and not hooks_only:
        unknown = only - set(GENERIC_SKILLS) - set(PROJECT_SKILLS)
        if unknown:
            print(f"不认识的技能：{'、'.join(sorted(unknown))}", file=sys.stderr)
            return 2

    n_write = n_skip = 0
    for name in want:
        src_dir = TEMPLATES / "skills" / name
        for src in sorted(src_dir.rglob("*")):
            if not src.is_file():
                continue
            dst = skills_root / name / src.relative_to(src_dir)
            if dst.exists() and not args.force:
                print(f"  跳过已存在的 {dst.relative_to(cfg.root)}（要覆盖加 --force）")
                n_skip += 1
                continue
            content = render(src.read_text(encoding="utf-8"), v)
            if args.dry_run:
                print(f"  [演练] 将写入 {dst.relative_to(cfg.root)}（{len(content)} 字节）")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8")
                print(f"  写入 {dst.relative_to(cfg.root)}")
            n_write += 1

    if args.with_hooks or hooks_only:   # --hooks-only 隐含 --with-hooks
        n_write += _install_hooks(cfg, v, args)

    # 人写的物料目录先建出来，否则「往哪写契约」得翻文档
    if not args.dry_run:
        for d in (cfg.acceptance_dir, cfg.requirements_dir, cfg.state_dir):
            d.mkdir(parents=True, exist_ok=True)

    print(f"\n{'演练完成' if args.dry_run else '完成'}：{n_write} 个文件"
          + (f"，跳过 {n_skip} 个已存在的" if n_skip else ""))
    if any(s in want for s in PROJECT_SKILLS):
        print(f"注意：{'、'.join(PROJECT_SKILLS)} 是**空模板**，里面的 TODO 要你自己填。"
              f"它们的价值就在于内容是本项目踩出来的，通用版没有意义。")
    return 0


def _install_hooks(cfg: Config, v: dict[str, str], args) -> int:
    hooks_dir = cfg.root / ".cursor" / "hooks"
    written = 0
    for name in ("mark-dirty.sh", "gate-guard.py"):
        src = TEMPLATES / "hooks" / name
        dst = hooks_dir / name
        if dst.exists() and not args.force:
            print(f"  跳过已存在的 {dst.relative_to(cfg.root)}（要覆盖加 --force）")
            continue
        content = render(src.read_text(encoding="utf-8"), v)
        if args.dry_run:
            print(f"  [演练] 将写入 {dst.relative_to(cfg.root)}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")
            dst.chmod(0o755)   # 没有可执行位的钩子会静默失效
            print(f"  写入 {dst.relative_to(cfg.root)}")
        written += 1

    cfg_path = cfg.root / ".cursor" / "hooks.json"
    hooks = {
        "version": 1,
        "hooks": {
            "afterFileEdit": [{"command": ".cursor/hooks/mark-dirty.sh", "timeout": 10}],
            "stop": [{"command": ".cursor/hooks/gate-guard.py", "timeout": 120,
                      "loop_limit": 3, "failClosed": False}],
        },
    }
    if cfg_path.exists() and not args.force:
        print(f"  跳过已存在的 {cfg_path.relative_to(cfg.root)}（要覆盖加 --force）；"
              f"需要的配置是：\n{json.dumps(hooks, ensure_ascii=False, indent=2)}")
        return written
    if args.dry_run:
        print(f"  [演练] 将写入 {cfg_path.relative_to(cfg.root)}")
    else:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(hooks, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"  写入 {cfg_path.relative_to(cfg.root)}")
    return written + 1
