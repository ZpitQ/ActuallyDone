"""贯穿全工具的数据模型。

只有两个概念需要先说清楚：

**未评估不是通过。** `DimResult.ran=False` 的维度不参与总分，页面上灰显。
任何一处「这个检查跑不了」都必须走这条路，绝不能返回一个 100 分的空结果——
那正是这个工具要防的事。

**回执是与代码绑死的事实。** 它由 gate 写，含受监视代码树的内容哈希；
「完成」的定义是存在一份哈希等于当前代码、且每步通过的回执。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEVERITIES = ("错误", "警告", "提示")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass
class Finding:
    """一条被发现的问题。where 要能让人直接跳过去看。"""

    severity: str
    where: str
    message: str


@dataclass
class Metric:
    """报告上的一个数字。tone 只影响配色：good / warnv / bad / 空。"""

    label: str
    value: str
    sub: str = ""
    tone: str = ""


@dataclass
class DimResult:
    key: str
    title: str
    ran: bool = True
    why_skipped: str = ""
    metrics: list[Metric] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0
    forced_score: int | None = None

    def add(self, severity: str, where: str, message: str) -> None:
        if severity not in SEVERITY_ORDER:
            raise ValueError(f"未知的级别 {severity}，只能是 {SEVERITIES}")
        self.findings.append(Finding(severity, where, message))

    def skip(self, why: str) -> "DimResult":
        """标记为本轮未评估。未评估的维度不计分，也不算通过。"""
        self.ran = False
        self.why_skipped = why
        return self

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "错误")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "警告")

    @property
    def score(self) -> int:
        if self.forced_score is not None:
            return self.forced_score
        return max(0, 100 - 15 * self.errors - 5 * self.warnings)


@dataclass
class Step:
    """门禁里的一步。stdout 留全文给解析用，回执里只存尾巴。"""

    name: str
    cwd: str
    argv: list[str]
    exit_code: int = -1
    ok: bool = False
    seconds: float = 0.0
    note: str = ""
    output_tail: str = ""
    stdout: str = field(default="", repr=False)

    def as_receipt(self) -> dict:
        return {k: v for k, v in vars(self).items() if k != "stdout"}


@dataclass
class TestResult:
    """一次测试运行的结构化结果，由适配器从原始输出里解析出来。

    skip_top 单独记：子用例名常带随机 ID、条数随数据浮动，
    拿总跳过数当基线会每轮误报，顶层跳过数才是稳定量。
    """

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    skip_top: int = 0
    passed_names: list[str] = field(default_factory=list)
    failed_names: list[str] = field(default_factory=list)
    skipped_names: list[str] = field(default_factory=list)
    coverage: float | None = None
    parsed: bool = True

    def as_dict(self) -> dict:
        return {
            "pass": self.passed, "fail": self.failed, "skip": self.skipped,
            "skip_top": self.skip_top,
            "passed_names": sorted(set(self.passed_names)),
            "failed_names": sorted(set(self.failed_names)),
            "skipped_names": sorted(set(self.skipped_names)),
            "coverage": self.coverage,
            "parsed": self.parsed,
        }


@dataclass
class FuncBody:
    """从源码里切出来的一个函数，供重复实现检测与断言检测使用。"""

    name: str
    line: int
    body: list[str]
