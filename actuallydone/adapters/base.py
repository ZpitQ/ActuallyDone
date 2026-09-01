"""适配器协议：把「这门语言/生态怎么算」与「健康度怎么判」分开。

一条铁律：**做不到的能力返回 None，不要返回空结果。**
返回 `set()` 会让上层以为「查过了，没问题」；返回 None 上层才知道该标「未评估」。
这两者在报告上是天差地别——一个是绿灯，一个是「这项没查」。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import FuncBody, TestResult

# 能力名，供上层判断某项检查能不能做
CAP_TESTS = "tests"            # 能解析测试输出、能列出测试名
CAP_SINGLE_TEST = "single"     # 能只跑指定的一条用例（抽查真跑用）
CAP_COVERAGE = "coverage"      # 能从 profile 里算函数级覆盖
CAP_FUNCS = "funcs"            # 能切分函数体（重复实现检测、无断言检测）
CAP_ROUTES = "routes"          # 能提取 HTTP 路由字面量
CAP_TABLES = "tables"          # 能提取建表语句里的表名
CAP_VIEWS = "views"            # 能提取前端页面文件名


class Adapter:
    """所有方法都可以不实现；不实现就等于「没有这个能力」。"""

    name = "generic"
    caps: set[str] = set()
    # 探测用：命中任一文件就认为这个生态存在
    markers: tuple[str, ...] = ()
    source_exts: tuple[str, ...] = ()

    def __init__(self, root: Path):
        self.root = root

    # ------------------------------------------------------------ 探测

    @classmethod
    def detect(cls, root: Path) -> list[str]:
        """返回命中的标志文件（相对路径）。空列表表示这个生态不存在。"""
        hits = []
        for m in cls.markers:
            found = next(iter(sorted(root.glob(m))), None)
            if found:
                hits.append(str(found.relative_to(root)))
        return hits

    def suggest_steps(self, hint_dir: str) -> list[dict]:
        """给探测用的默认门禁步骤。hint_dir 是这个生态的根（相对仓库根）。"""
        return []

    def suggest_watch(self, hint_dir: str) -> tuple[list[str], list[str]]:
        """返回 (受监视目录, 后缀)。"""
        return ([], list(self.source_exts))

    # ------------------------------------------------------------ 测试

    def parse_test_output(self, text: str) -> TestResult | None:
        return None

    def parse_test_run(self, text: str, *, cwd: Path | None = None,
                       since: float | None = None) -> TestResult | None:
        """带运行上下文的解析。默认忽略 cwd / since，退回 parse_test_output。

        只有要从磁盘读报告（JUnit XML 等）的生态才覆盖它：
        cwd 是步骤的工作目录，since 是这一轮开始的墙上时钟，用来丢掉上一轮残留的报告。
        """
        return self.parse_test_output(text)

    def test_names(self, roots: list[Path]) -> set[str] | None:
        return None

    def test_files(self, roots: list[Path]) -> list[Path]:
        return []

    def single_test_argv(self, name: str) -> list[str] | None:
        """只跑这一条用例的命令。做不到就返回 None，上层会标「未评估」。"""
        return None

    def related_tests(self, rel_paths: list[str]) -> list[str] | None:
        """按改动文件找相关用例名。None = 适配器不会找；空列表 = 找过了没有。

        空列表不能当成绿：上层必须回推「找不到相关用例」，不许退回全量、
        也不许空跑冒充通过。
        """
        return None

    def related_test_argv(self, names: list[str]) -> list[str] | None:
        """一次跑这批相关用例的临时命令。做不到返回 None。

        这是临时 argv，不写进 adone.toml，判据锁不读它。
        默认只会在恰好一条时退回 single_test_argv。
        """
        if len(names) == 1:
            return self.single_test_argv(names[0])
        return None

    def iter_test_funcs(self, path: Path) -> list[FuncBody]:
        """测试文件里的用例函数，供无断言检测用。"""
        return []

    def is_assertionless(self, body: list[str]) -> bool:
        return False

    def skip_sites(self, text: str) -> int:
        """源码里「跳过用例」的写法出现了几次。"""
        return 0

    # ------------------------------------------------------------ 代码

    def iter_funcs(self, path: Path) -> list[FuncBody]:
        return []

    def zero_cover(self, profile: Path, cwd: Path) -> tuple[int, int] | None:
        """返回 (零覆盖函数数, 总函数数)。"""
        return None

    def routes(self, target: Path) -> set[str] | None:
        return None

    def views(self, target: Path) -> set[str] | None:
        return None


# ------------------------------------------------------------------ 共用工具

def read(path: Path) -> str:
    from ..textio import read as read_text
    return read_text(path)


def companion_stems(stem: str) -> tuple[str, ...]:
    """实现文件 stem 对应的常见测试文件名（不含后缀）。"""
    return (f"{stem}Test", f"{stem}Tests", f"Test{stem}",
            f"{stem}_test", f"{stem}_tests", f"test_{stem}")


def brace_funcs(lines: list[str], start_re: re.Pattern, name_of) -> list[FuncBody]:
    """按大括号配平切函数，Go / TS / JS 都能用。

    去注释、去空白后再收集，因此「同一段逻辑换个名字放到另一个文件」也能被认出来。
    """
    out: list[FuncBody] = []
    i = 0
    n = len(lines)
    while i < n:
        if not start_re.match(lines[i]):
            i += 1
            continue
        start = i
        depth = 0
        opened = False
        body: list[str] = []
        while i < n:
            raw = lines[i]
            stripped = re.sub(r"//.*$", "", raw).strip()
            depth += raw.count("{") - raw.count("}")
            if "{" in raw:
                opened = True
            if stripped:
                body.append(stripped)
            i += 1
            if opened and depth <= 0:
                break
        inner = body[1:-1] if len(body) > 2 else []
        out.append(FuncBody(name=name_of(lines[start]), line=start + 1, body=inner))
    return out
