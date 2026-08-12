"""造微型项目的脚手架。

用真实文件而不是 mock：这些检查的对象就是文件系统，mock 掉之后测的是 mock 自己。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actuallydone.config import Config  # noqa: E402

GO_MAIN = """package internal

func Add(a, b int) int { return a + b }

func Sub(a, b int) int { return a - b }
"""

GO_TEST = """package internal

import "testing"

func TestAdd(t *testing.T) {
\tif Add(1, 2) != 3 {
\t\tt.Fatal("加法不对")
\t}
}

func TestNoAssert(t *testing.T) {
\t_ = Add(1, 2)
}

func TestSkipped(t *testing.T) {
\tt.Skip("暂时跳过")
}
"""

GO_TEST_OUTPUT = """=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestSub
=== RUN   TestSub/负数
    --- PASS: TestSub/负数 (0.00s)
--- PASS: TestSub (0.01s)
=== RUN   TestSkipped
--- SKIP: TestSkipped (0.00s)
=== RUN   TestBroken
--- FAIL: TestBroken (0.00s)
FAIL
coverage: 85.9% of statements
"""

NODE_TEST_OUTPUT = """ \u2713 src/order.test.ts > \u62d2\u7edd\u8d1f\u6570\u4ef7\u683c 3ms
 \u2713 src/order.test.ts > \u63a5\u53d7\u96f6\u4ef7 1ms
 \u00d7 src/order.test.ts > \u5e93\u5b58\u4e0d\u8db3\u65f6\u4e0b\u5355 5ms

 Tests  1 failed | 2 passed (3)
"""


class ProjectCase(unittest.TestCase):
    """每个用例一个临时项目，测完即删。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="adone-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def make_go_project(self) -> None:
        self.write("go.mod", "module fixture\n\ngo 1.22\n")
        self.write("internal/calc.go", GO_MAIN)
        self.write("internal/calc_test.go", GO_TEST)

    def make_node_project(self) -> None:
        self.write("package.json",
                   '{"name":"fixture","scripts":{"build":"tsc","test":"vitest"}}')
        self.write("src/order.ts", "export function order() { return 1 }\n")
        self.write("src/order.test.ts",
                   'it("拒绝负数价格", () => { expect(1).toBe(1) })\n')
        self.write("src/OrderView.vue", "<template><div/></template>\n")

    def config(self, **over) -> Config:
        data = {
            "project": {"name": "fixture", "ecosystems": ["go"]},
            "gate": {"watch_roots": ["internal"], "watch_exts": [".go"],
                     "min_tree_files": 1, "step": []},
            "tests": {"adapter": "go", "roots": ["internal"]},
        }
        for k, v in over.items():
            data.setdefault(k, {})
            data[k] = {**data.get(k, {}), **v} if isinstance(v, dict) else v
        return Config.from_dict(self.root, data)
