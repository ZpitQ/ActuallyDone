"""detect --merge：增量追加，不冲掉已有阈值。"""

from __future__ import annotations

from actuallydone.detect import detect, merge_config, render_config
from tests.helpers import ProjectCase


class TestConfigMerge(ProjectCase):
    def _go_config(self) -> str:
        self.make_go_project()
        text = render_config(detect(self.root))
        # 手填阈值：合并之后这两行必须原样还在
        text = text.replace("# threshold = 0.0", "threshold = 72.5")
        text = text.replace("min_tree_files = 1         # 请确认：这是最宽松的值，等于没有保护",
                            "min_tree_files = 40")
        self.write("adone.toml", text)
        return text

    def test_追加步骤幂等且不碰已有阈值(self):
        old = self._go_config()
        self.make_maven_project()
        got = detect(self.root)
        self.assertIn("java", got.ecosystems)
        new, notes = merge_config(old, got)
        self.assertIn("threshold = 72.5", new)
        self.assertIn("min_tree_files = 40", new)
        self.assertIn('name = "mvn test"', new)
        self.assertIn('adapter = "java"', new)
        again, notes2 = merge_config(new, got)
        self.assertEqual(again, new)
        self.assertTrue(any("没有新增" in n for n in notes2))

    def test_补ecosystems与watch数组(self):
        old = self._go_config()
        self.make_maven_project()
        new, notes = merge_config(old, detect(self.root))
        self.assertIn('"java"', new)
        self.assertIn('".java"', new)
        self.assertTrue(any("ecosystems" in n for n in notes))

    def test_多行数组不猜报成待办(self):
        old = self._go_config()
        old = old.replace(
            'watch_exts = [".go"]',
            'watch_exts = [\n  ".go",\n]')
        self.write("adone.toml", old)
        self.make_maven_project()
        new, notes = merge_config(old, detect(self.root))
        self.assertTrue(any("不是单行数组" in n for n in notes))
        # 没被改成单行猜测
        self.assertIn('watch_exts = [', new)
        self.assertIn('  ".go",', new)

    def test_默认不改tests_adapter(self):
        old = self._go_config()
        self.make_maven_project()
        new, notes = merge_config(old, detect(self.root))
        self.assertIn('adapter = "go"', new)
        self.assertTrue(any("--adopt-tests" in n for n in notes))

    def test_adopt_tests才改适配器(self):
        old = self._go_config()
        self.make_maven_project()
        new, notes = merge_config(old, detect(self.root), adopt_tests=True)
        self.assertIn('adapter = "java"', new)
        self.assertTrue(any("--adopt-tests" in n for n in notes))
        self.assertIn("coverage.source 改成", "\n".join(notes))
