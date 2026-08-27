"""把技能与钩子模板渲染进项目。

技能必须落在 Agent 平台认的位置（Cursor 只认 `.cursor/skills/`），所以工具不能
「自带技能」，只能渲染。渲染时要替掉模板里的占位符——把「85% 是当前实测水位」
原样抄进别人的项目，就是在替他们说谎。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from .config import Config

TEMPLATES = Path(__file__).resolve().parent / "templates"

# 随包发布的通用技能（方法通用，内容可参数化）
GENERIC_SKILLS = ("completion-gate", "acceptance-contract", "test-integrity",
                  "verified-delivery", "independent-check")
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
    "java": {
        "ASSERT_API": "assertEquals / assertThat / andExpect",
        "SKIP_API": "@Disabled / assumeTrue",
        "TEST_FUNC_FORM": "用例名（`CalcTest#testAdd`）",
        "TEST_NAME_EXAMPLE": "CalcTest#testAdd",
        "IMPL_EXAMPLE": "<实现文件>.java:168",
        "FMT_CMD": "mvn -B spotless:check 通过",
        "BUILD_CMD": "mvn -B -ntp test 通过",
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
        # .cmd 启动器用未加引号的 Windows 路径；空串表示装的时候 PATH 里没有
        "ADONE_CMD_WIN": (shutil.which("adone") or "").replace("/", "\\"),
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
        "WATCH_ROOTS_PY": json.dumps(roots, ensure_ascii=False),
        "WATCH_EXTS_PY": json.dumps(exts, ensure_ascii=False),
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


def _write(dst: Path, content: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content, encoding="utf-8")


def _write_cmd(dst: Path, content: str) -> None:
    """cmd.exe 认 CRLF。从 Mac 写出的 LF 批处理，有的 Windows 会当空文件跳过。

    不要用于 hook-launch.cmd：那是 cmd/bash 双语，heredoc 遇 CRLF 合不上。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = content.replace("\r\n", "\n").replace("\n", "\r\n")
    if not text.endswith("\r\n"):
        text += "\r\n"
    dst.write_bytes(text.encode("utf-8"))


def _write_lf(dst: Path, content: str) -> None:
    """按 LF 落盘，不走 write_text（Windows 上会变成 CRLF）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = content.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    dst.write_bytes(text.encode("utf-8"))


def _write_failed(cfg: Config, dst, err: OSError, n_done: int) -> int:
    """写不进去时给一句人话。

    原来这里直接把 OSError 抛到顶，用户看到的是一屏 Python 堆栈；更糟的是安装
    到一半停下，前面写成功的文件还在，得自己判断装了多少。
    """
    where = dst if dst else "目标目录"
    try:
        where = Path(where).relative_to(cfg.root)
    except (TypeError, ValueError):
        pass
    print(f"\n写不进去 {where}：{err.strerror or err}", file=sys.stderr)
    print(f"这一步之前已经写了 {n_done} 个文件，安装没有完成。"
          f"多半是权限或只读挂载的问题，处理完重跑一次（重跑是安全的）。", file=sys.stderr)
    return 1


def cmd_install(cfg: Config, args) -> int:
    v = variables(cfg)
    skills_root = Path(args.skills_dir).resolve() if args.skills_dir else cfg.skills_dir
    hooks_only = getattr(args, "hooks_only", False)
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    if only and hooks_only:
        # 静默忽略用户明确给出的参数，正是这个工具存在的理由的反面
        print("--hooks-only 只装钩子，不装技能，和 --only 一起给没有意义：去掉一个再来",
              file=sys.stderr)
        return 2
    want = [] if hooks_only else [s for s in (*GENERIC_SKILLS, *PROJECT_SKILLS)
                                  if only is None or s in only]
    if only:
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
                try:
                    _write(dst, content)
                except OSError as e:
                    return _write_failed(cfg, dst, e, n_write)
                print(f"  写入 {dst.relative_to(cfg.root)}")
            n_write += 1

    if args.with_hooks or hooks_only:   # --hooks-only 隐含 --with-hooks
        try:
            n_write += _install_hooks(cfg, v, args)
        except OSError as e:
            return _write_failed(cfg, getattr(e, "filename", None), e, n_write)

    # 人写的物料目录先建出来，否则「往哪写契约」得翻文档
    if not args.dry_run:
        for d in (cfg.acceptance_dir, cfg.requirements_dir, cfg.state_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return _write_failed(cfg, d, e, n_write)

    print(f"\n{'演练完成' if args.dry_run else '完成'}：{n_write} 个文件"
          + (f"，跳过 {n_skip} 个已存在的" if n_skip else ""))
    if any(s in want for s in PROJECT_SKILLS):
        print(f"注意：{'、'.join(PROJECT_SKILLS)} 是**空模板**，里面的 TODO 要你自己填。"
              f"它们的价值就在于内容是本项目踩出来的，通用版没有意义。")
    return 0


def hooks_report(cfg: Config) -> tuple[list[str], list[str]]:
    """已装钩子的体检，返回（说明行，问题）。

    钩子没装不算问题——它是可选的。装了却失效才算：钩子失效的样子是「什么都不发生」，
    和「一切正常」在终端里完全一样，只能靠主动去核。这套检查是今天真实踩过的三个坑：
    命令找不到、可执行位丢了、配置改了而钩子还是旧的。
    """
    lines: list[str] = []
    problems: list[str] = []
    hooks_json = cfg.root / ".cursor" / "hooks.json"
    hooks_dir = cfg.root / ".cursor" / "hooks"
    launchers = [hooks_dir / n for n in OUR_LAUNCHERS]
    leftover_py = [hooks_dir / n for n in OUR_SCRIPTS if (hooks_dir / n).is_file()]
    if not hooks_json.exists() and not any(p.exists() for p in launchers) and not leftover_py:
        lines.append("  钩子：未安装（要装跑 adone install --with-hooks）")
        return lines, problems

    events = _read_json(hooks_json).get("hooks") or {}
    registered = json.dumps(events, ensure_ascii=False)

    if leftover_py:
        names = "、".join(p.name for p in leftover_py)
        problems.append(f"{names} 还在 .cursor/hooks/ 里：Windows 会按文件关联用编辑器"
                        f"打开它们（每次弹出 gate-guard.py 就是这个）。"
                        f"重渲 adone install --hooks-only --force 会删掉这些 .py")

    if os.name == "nt":
        for name in OUR_EXES:
            if not (hooks_dir / name).is_file():
                problems.append(f"钩子 {name} 不在 .cursor/hooks/ 里：CreateProcess "
                                f"不能直接跑 .cmd（终端里手跑可以，Cursor 调不起来）。"
                                f"重跑 adone install --hooks-only --force")
            elif name not in registered:
                problems.append(f"{name} 在磁盘上，但 .cursor/hooks.json 里没登记它，等于没装")

    for name in LEGACY_SCRIPTS:
        if name in registered:
            problems.append(f"hooks.json 里还登记着旧版 {name}（bash 版，Windows 上没有 "
                            f"bash 也没有 jq，Cursor 起不动它）："
                            f"重渲一下 adone install --hooks-only --force")

    for cmd in _our_commands(events):
        problems += _launch_problems(cfg, cmd)

    found = _resolve_adone(cfg.root, adone_entry(cfg), shutil.which("adone") or "")
    if found:
        lines.append(f"  钩子：已装，跑门禁时用 {found} hook")
    else:
        problems.append("钩子找不到 adone（仓库内入口、PATH 都不行）："
                        "它会把「门禁没跑成」推回给 Agent，等于门禁形同虚设。"
                        "装好 adone 后重跑 adone install --hooks-only --force")
    return lines, problems


def _script_registered(name: str, registered: str) -> bool:
    """hooks.json 里登记的可能是 .py，Windows 上则是同名的 .cmd / .exe。"""
    stem = Path(name).stem
    return (name in registered or f"{stem}.cmd" in registered
            or f"{stem}.bat" in registered or f"{stem}.exe" in registered)


def find_hook_exe(name: str) -> Path | None:
    """本机用来复制进 .cursor/hooks/<name>.exe 的 PE。

    优先专用入口 adone-hook-<name>.exe（setuptools 烧好的），
    否则用同目录的 adone.exe（cli 按 argv[0] 文件名分发）。
    """
    dedicated = f"adone-hook-{name}"
    for label in (dedicated, "adone"):
        w = shutil.which(label) or ""
        if not w:
            continue
        p = Path(w)
        if p.suffix.lower() == ".exe" and p.is_file():
            if label == dedicated:
                return p
            sib = p.with_name(f"{dedicated}.exe")
            return sib if sib.is_file() else p
        exe = p.with_suffix(".exe")
        if exe.is_file():
            if label == dedicated:
                return exe
            sib = exe.with_name(f"{dedicated}.exe")
            return sib if sib.is_file() else exe
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    for d in (
        home / ".local" / "bin",
        local / "pipx" / "venvs" / "actuallydone" / "Scripts",
        home / ".local" / "pipx" / "venvs" / "actuallydone" / "Scripts",
        home / "AppData" / "Roaming" / "Python" / "Scripts",
        local / "Programs" / "Python" / "Scripts",
    ):
        for cand in (d / f"adone-hook-{name}.exe", d / "adone.exe"):
            if cand.is_file():
                return cand
    return None


def windows_opens_hook_as_file(cmd: str) -> bool:
    """这条命令在 Windows 上会不会被当成「打开文件」而不是「执行脚本」。

    Cursor 把 hooks.json 的 command 交给操作系统去启动。登记 `.py` 时，
    Windows 按文件关联用默认应用打开它——Cursor 自己就是 .py 的默认应用，
    于是每次弹出 gate-guard.py，脚本一行都没跑。必须登记 .cmd。
    """
    if not any(n in cmd for n in OUR_SCRIPTS):
        return False
    token = cmd.strip().split()[0] if cmd.strip() else ""
    return not token.lower().endswith((".cmd", ".bat"))


def windows_hook_never_starts(cmd: str) -> bool:
    """这条命令在 Windows 上 CreateProcess 起不来。

    CreateProcess 只能起 PE（.exe）。`.cmd` / `.bat` 必须由 cmd.exe 代跑——
    终端里手跑可以，Cursor 把 command 当可执行文件名去启动时不行。
    `cmd /c …cmd` 整串当文件名，一样起不来。所以必须登记一条 .exe 路径。
    """
    c = cmd.strip().lower()
    if not c:
        return False
    if c.startswith("cmd ") and "/c" in c:
        return True
    token = c.split()[0]
    return token.endswith((".cmd", ".bat"))


def _our_commands(events: dict) -> list[str]:
    names = (*OUR_SCRIPTS, *OUR_LAUNCHERS, *OUR_EXES, *LEGACY_SCRIPTS)
    return [str(h.get("command") or "")
            for hooks in (events or {}).values() for h in (hooks or [])
            if any(n in str(h.get("command") or "") for n in names)]


def _launch_problems(cfg: Config, cmd: str) -> list[str]:
    """这条登记在本机到底起不起得来。

    以前这里只查可执行位（`os.access(X_OK)`）——那在 Windows 上对任何存在的文件
    都为真，于是「钩子已装」和「钩子从没被触发过」在体检里长得一模一样，
    Java 团队就是这么被坑的：Agent 改完代码没人提醒，doctor 却说钩子已装。
    """
    from .gate import resolve_cmd
    if os.name == "nt" and windows_opens_hook_as_file(cmd):
        return [f"钩子命令「{cmd}」在 Windows 上会打开文件而不是执行："
                f"系统按文件关联用编辑器弹出 .py（每次看到 gate-guard.py "
                f"被打开就是这个）。重渲 adone install --hooks-only --force，"
                f"会改成登记 .cmd 启动器"]
    if os.name == "nt" and windows_hook_never_starts(cmd):
        return [f"钩子命令「{cmd}」在 Windows 上根本起不来："
                f"CreateProcess 不能直接跑 .cmd，也不能把 `cmd /c …` 整串当文件名。"
                f"终端里手跑可以，Cursor 调不起来，.adone 里不会有 hook.log。"
                f"重渲 adone install --hooks-only --force，会改成登记 .exe"]

    parts = cmd.split()
    if parts and parts[0].lower() in ("cmd", "cmd.exe"):
        parts = parts[2:] if len(parts) > 2 and parts[1].lower() in ("/c", "/k") else parts[1:]
    if not parts:
        return []

    if len(parts) == 1:
        p = cfg.root / parts[0]
        if parts[0].lower().endswith(".exe"):
            if not p.is_file():
                return [f"钩子命令「{cmd}」指向的 {parts[0]} 不存在："
                        f"重跑 adone install --hooks-only --force"]
            return []
        if parts[0].lower().endswith((".cmd", ".bat")):
            if not p.is_file():
                return [f"钩子命令「{cmd}」指向的 {parts[0]} 不存在"]
            return []
        # 只有脚本路径：靠 shebang 加可执行位启动，这是 POSIX 才成立的约定
        if os.name == "nt":
            return [f"钩子命令「{cmd}」在 Windows 上起不动：shebang 与可执行位是 POSIX "
                    f"才有的东西。重渲一下 adone install --hooks-only --force"]
        if p.exists() and not os.access(p, os.X_OK):
            return [f"钩子 {parts[0]} 没有可执行位，Cursor 起不动它（chmod +x 或重装钩子）"]
        return []

    out: list[str] = []
    if resolve_cmd(parts[0], cfg.root) is None:
        out.append(f"钩子命令「{cmd}」里的 {parts[0]} 找不到：Cursor 起不动它，"
                   f"钩子会静默失效（装上它，或重渲 adone install --hooks-only --force）")
    script = next((p for p in parts if p.endswith((".py", ".sh"))), "")
    if script and not (cfg.root / script).is_file():
        out.append(f"钩子命令「{cmd}」指向的 {script} 不存在")
    return out


def _const(text: str, name: str) -> str:
    m = re.search(rf'^{name}\s*=\s*"([^"]*)"', text, re.M)
    return m.group(1) if m else ""


def _resolve_adone(root: Path, entry: str, cmd: str) -> str:
    """复刻钩子运行时的查找顺序。钩子是生成物，不能 import 这里的代码，只能对齐。"""
    if entry and (root / entry).is_file():
        return str(root / entry)
    if cmd and Path(cmd).is_file():
        return cmd
    on_path = shutil.which("adone")
    if on_path:
        return on_path
    for d in ("~/.local/bin", "~/.local/pipx/venvs/actuallydone/bin",
              "/opt/homebrew/bin", "/usr/local/bin",
              "~/.local/pipx/venvs/actuallydone/Scripts",
              "~/AppData/Roaming/Python/Scripts",
              "~/AppData/Local/Programs/Python/Scripts"):
        for name in ("adone", "adone.exe", "adone.cmd", "adone.bat"):
            cand = Path(d).expanduser() / name
            if cand.is_file():
                return str(cand)
    return ""


OUR_SCRIPTS = ("mark-dirty.py", "gate-guard.py")
OUR_LAUNCHERS = ("mark-dirty.cmd", "gate-guard.cmd")
OUR_EXES = ("mark-dirty.exe", "gate-guard.exe")
# 早先 afterFileEdit 挂的是 bash 版：Windows 上没有 bash 也没有 jq，Cursor 起不动它。
# v1.3.3 又改成登记 .py / `cmd /c py -3 …py`：Windows 按文件关联打开 .py。
# v1.3.4–1.3.7 登记 .cmd：CreateProcess 不能直接跑批处理，手跑可以、钩子不触发。
# 升级时都要从 hooks.json 里摘掉，否则留着一条永远失败的登记
LEGACY_SCRIPTS = ("mark-dirty.sh",)


def hook_python() -> str:
    """钩子里用哪个解释器。

    不烧 sys.executable：hooks.json 是要提交进仓库的，
    /opt/homebrew/opt/python@3.13/bin/python3.13 换台机器就是错的。
    """
    if os.name == "nt":
        # py 是官方安装器带的启动器；Windows 商店那个 python 别名会打开应用商店
        return "py -3" if shutil.which("py") else "python"
    return "python3"


def hook_command(name: str, cfg: Config | None = None) -> str:
    """本机该写进 hooks.json 的 command。整条命令里不能出现 .py 路径。

    Windows 上 Cursor 把 command 当可执行文件名交给 CreateProcess。
    CreateProcess 只能起 .exe：`.cmd` 手跑可以（壳会转给 cmd.exe），Cursor
    直接 CreateProcess 则失败——1.3.4 到 1.3.7 都是这个，.adone 里没有 hook.log。
    `cmd /c …cmd` 整串当文件名，一样起不来。所以只写一条 .exe 相对路径。
    POSIX 上走 `python3 -m actuallydone hook …` 或仓库内入口，同样不写 .py 路径。
    """
    if os.name == "nt":
        return f".cursor/hooks/{name}.exe"
    if cfg is not None:
        entry = adone_entry(cfg)
        if entry:
            return f"{hook_python()} {entry} hook {name}"
    return f"{hook_python()} -m actuallydone hook {name}"


def our_hooks(cfg: Config | None = None) -> dict:
    """本机该写进 hooks.json 的登记。命令随平台变，所以是函数而不是常量。"""
    return {
        "sessionStart": [
            {"command": hook_command("mark-dirty", cfg), "timeout": 10}],
        "afterFileEdit": [
            {"command": hook_command("mark-dirty", cfg), "timeout": 10}],
        "stop": [
            {"command": hook_command("gate-guard", cfg), "timeout": 120,
             "loop_limit": 3, "failClosed": False}],
    }


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}   # 读不动或不是合法 JSON，就当没有：下面会重新生成一份完整的


def merge_hooks(existing: dict, cfg: Config | None = None) -> tuple[dict, int]:
    """把我们的两个钩子并进已有的 hooks.json，返回（合并结果，保住的外来条目数）。

    以前这里是整份覆盖。别人在同一个文件里配了 beforeShellExecution 之类的钩子，
    一次 `install --force` 就没了——而它们失效的样子同样是「安静地什么都不发生」。
    """
    out = dict(existing) if existing else {}
    out["version"] = out.get("version", 1)
    events = dict(out.get("hooks") or {})
    ours_all = our_hooks(cfg)
    mine = (*OUR_SCRIPTS, *OUR_LAUNCHERS, *OUR_EXES, *LEGACY_SCRIPTS,
            "hook mark-dirty", "hook gate-guard")
    kept = 0
    for event, ours in ours_all.items():
        foreign = [h for h in (events.get(event) or [])
                   if not any(s in str(h.get("command", "")) for s in mine)]
        kept += len(foreign)
        events[event] = foreign + [dict(h) for h in ours]
    for event, hooks in (out.get("hooks") or {}).items():
        if event not in ours_all:
            kept += len(hooks or [])
    out["hooks"] = events
    return out, kept


def _install_hooks(cfg: Config, v: dict[str, str], args) -> int:
    hooks_dir = cfg.root / ".cursor" / "hooks"
    written = 0

    # Windows：CreateProcess 只能起 .exe。把 adone.exe / 专用入口复制成
    # .cursor/hooks/<name>.exe，hooks.json 只写这一条相对路径。
    # .cmd 仍写出，方便在终端里手跑对照；Cursor 不再登记它。
    launcher = render((TEMPLATES / "hooks" / "hook-launch.cmd").read_text(encoding="utf-8"), v)
    for name in OUR_LAUNCHERS:
        dst = hooks_dir / name
        if dst.exists() and not args.force:
            print(f"  跳过已存在的 {dst.relative_to(cfg.root)}（要覆盖加 --force）")
            continue
        if args.dry_run:
            print(f"  [演练] 将写入 {dst.relative_to(cfg.root)}")
        else:
            _write_lf(dst, launcher)
            print(f"  写入 {dst.relative_to(cfg.root)}")
        written += 1

    for stem, dest_name in (("mark-dirty", "mark-dirty.exe"),
                            ("gate-guard", "gate-guard.exe")):
        dst = hooks_dir / dest_name
        src = find_hook_exe(stem)
        if dst.exists() and not args.force:
            print(f"  跳过已存在的 {dst.relative_to(cfg.root)}（要覆盖加 --force）")
            continue
        if src is None:
            if os.name == "nt":
                print(f"  找不到 {dest_name} 的来源（adone.exe / adone-hook-{stem}.exe）："
                      f"hooks.json 会登记它，但 Cursor 起不来。先 adone upgrade 再 "
                      f"adone install --hooks-only --force", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"  [演练] 将复制 {src} → {dst.relative_to(cfg.root)}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  复制 {dst.relative_to(cfg.root)} ← {src}")
        written += 1

    # .cursor/hooks/*.py 在 Windows 上会被当成要打开的文件。逻辑已经进了
    # `adone hook`，这些副本必须删掉，否则还会弹出 gate-guard.py。
    for name in (*OUR_SCRIPTS, *LEGACY_SCRIPTS):
        stale = hooks_dir / name
        if not stale.is_file():
            continue
        if args.dry_run:
            print(f"  [演练] 将删掉 {stale.relative_to(cfg.root)}（Windows 会打开这个文件）")
        else:
            stale.unlink(missing_ok=True)
            print(f"  删掉 {stale.relative_to(cfg.root)}（钩子逻辑改走 adone hook，"
                  f"这个文件留着会被编辑器打开）")

    cfg_path = cfg.root / ".cursor" / "hooks.json"
    if cfg_path.exists() and not args.force:
        print(f"  跳过已存在的 {cfg_path.relative_to(cfg.root)}（要覆盖加 --force，"
              f"会保留你自己写在里面的其他钩子）；需要的配置是：\n"
              f"{json.dumps(our_hooks(cfg), ensure_ascii=False, indent=2)}")
        return written

    merged, kept = merge_hooks(_read_json(cfg_path), cfg)
    if args.dry_run:
        print(f"  [演练] 将写入 {cfg_path.relative_to(cfg.root)}"
              + (f"（保留其中 {kept} 条不属于 adone 的钩子）" if kept else ""))
    else:
        _write(cfg_path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
        print(f"  写入 {cfg_path.relative_to(cfg.root)}"
              + (f"（保留其中 {kept} 条不属于 adone 的钩子）" if kept else ""))
    return written + 1
