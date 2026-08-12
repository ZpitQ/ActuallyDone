"""维度注册表。

权重可以在 adone.toml 的 [score.weights] 里改；总分只按**本轮真跑过**的维度加权，
跳过的维度在页面上灰显成「未评估」，标题旁写明覆盖了几分之几——
这样 `--only skills` 拿 100 分也刷不出一个虚高的总分。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import code, materials, probes, requirements, skills, tests


@dataclass
class Dimension:
    key: str
    title: str
    weight: float
    cost: str
    fn: Callable
    in_default: bool = True


DIMENSIONS: list[Dimension] = [
    Dimension("skills", "技能沉淀", 1.0, "秒级", skills.run),
    Dimension("tests", "测试与覆盖率", 2.0, "秒级（--all 时重跑门禁）", tests.run),
    Dimension("code", "代码质量", 1.0, "数秒", code.run),
    Dimension("requirements", "需求台账", 2.0, "秒级", requirements.run),
    Dimension("materials", "AI 物料", 1.5, "秒级", materials.run),
    Dimension("probes", "业务不变量", 1.0, "取决于探针，可能要服务在跑且会写数据",
              probes.run, in_default=False),
]
DIM_BY_KEY = {d.key: d for d in DIMENSIONS}
