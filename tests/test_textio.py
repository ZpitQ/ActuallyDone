"""源码编码：GBK 项目不能被按 UTF-8 读成乱码。

GBK 的尾字节范围含 ASCII，`亄`（81 7B）按 UTF-8 解会漏出一个 `{`。
大括号一多，扫测试方法就会切错函数体——扫不到不会报错，只会少认几条用例。
"""

from __future__ import annotations

from io import StringIO
from contextlib import redirect_stdout

from actuallydone import textio
from actuallydone.config import Config
from actuallydone.detect import detect, render_config
from tests.helpers import ProjectCase


class TestDecode(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(textio.set_default, "auto")

    def test_auto_两种编码逐个文件试(self):
        textio.set_default("auto")
        u = self.root / "u.java"
        g = self.root / "g.java"
        u.write_bytes("// 退款流程\n".encode("utf-8"))
        g.write_bytes("// 退款流程\n".encode("gbk"))
        self.assertEqual(textio.read(u), "// 退款流程\n")
        self.assertEqual(textio.read(g), "// 退款流程\n")

    def test_gbk尾字节不再漏出大括号(self):
        textio.set_default("gbk")
        p = self.root / "a.java"
        p.write_bytes("class T { String s = \"亄乗\"; }\n".encode("gbk"))
        got = textio.read(p)
        self.assertEqual(got.count("{"), 1)
        self.assertEqual(got.count("\\"), 0)
        self.assertIn("亄乗", got)
        # 按 UTF-8 硬读就会凭空多出括号与反斜杠，这正是要避免的
        bad = p.read_bytes().decode("utf-8", "replace")
        self.assertGreater(bad.count("{") + bad.count("\\"), 1)

    def test_指定utf8时坏字节也不抛异常(self):
        textio.set_default("utf-8")
        p = self.root / "b.java"
        p.write_bytes(b"class T {}\n\xff\xfe\xfa")
        self.assertIn("class T {}", textio.read(p))

    def test_设成gbk也不会读坏utf8文件(self):
        """GB18030 几乎什么字节都解得出来，配了 gbk 就先按 gbk 解会静悄悄毁掉混着的 UTF-8。"""
        textio.set_default("gbk")
        p = self.root / "u.java"
        p.write_bytes("// 退款流程：不含税\n".encode("utf-8"))
        self.assertEqual(textio.read(p), "// 退款流程：不含税\n")
        self.assertEqual(textio.candidates()[0], "utf-8-sig")

    def test_读不到文件返回空串(self):
        self.assertEqual(textio.read(self.root / "没有这个文件.java"), "")


class TestSniff(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(textio.set_default, "auto")

    def test_纯ascii不投票(self):
        self.write("a.java", "class A {}\n")
        enc, tally = textio.sniff([self.root / "a.java"])
        self.assertEqual(enc, "utf-8")
        self.assertEqual(tally["ascii"], 1)

    def test_混编码建议auto(self):
        (self.root / "u.java").write_bytes("// 中文\n".encode("utf-8"))
        (self.root / "g.java").write_bytes("// 中文\n".encode("gbk"))
        enc, _ = textio.sniff([self.root / "u.java", self.root / "g.java"])
        self.assertEqual(enc, "auto")

    def test_全是gbk建议gbk(self):
        (self.root / "g.java").write_bytes("// 中文\n".encode("gbk"))
        enc, tally = textio.sniff([self.root / "g.java"])
        self.assertEqual(enc, "gbk")
        self.assertEqual(tally["gbk"], 1)


class TestConfigWiring(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(textio.set_default, "auto")

    def test_加载配置会下发编码(self):
        self.write("adone.toml",
                   "version = 1\n[project]\nname = 'f'\n"
                   "source_encoding = 'gbk'\n")
        textio.set_default("utf-8")
        Config.load(self.root)
        self.assertEqual(textio.get_default(), "gb18030")

    def test_老配置没有这一项就是auto(self):
        self.write("adone.toml", "version = 1\n[project]\nname = 'f'\n")
        cfg = Config.load(self.root)
        self.assertEqual(cfg.get("project.source_encoding"), "auto")
        self.assertEqual(textio.get_default(), "auto")

    def test_配置文件不是utf8时给人话(self):
        from actuallydone.config import ConfigError
        (self.root / "adone.toml").write_bytes(
            "version = 1\n[project]\nname = '订单'\n".encode("gbk"))
        with self.assertRaises(ConfigError) as ctx:
            Config.load(self.root)
        self.assertIn("UTF-8", str(ctx.exception))
        self.assertIn("source_encoding", str(ctx.exception))


class TestDetectEncoding(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(textio.set_default, "auto")

    def test_探测gbk项目并写进配置(self):
        self.make_go_project()
        for p in self.root.rglob("*.go"):
            p.write_bytes(p.read_text(encoding="utf-8").encode("gbk"))
        (self.root / "internal" / "calc.go").write_bytes(
            "package internal\n\n// 计价：不含税\nfunc Add() {}\n".encode("gbk"))
        with redirect_stdout(StringIO()):
            got = detect(self.root)
        self.assertEqual(got.source_encoding, "gbk")
        text = render_config(got)
        self.assertIn('source_encoding = "gbk"', text)
        self.assertIn("请确认", text.split("source_encoding")[1].splitlines()[0])

    def test_探测utf8项目(self):
        self.make_go_project()
        with redirect_stdout(StringIO()):
            got = detect(self.root)
        self.assertEqual(got.source_encoding, "utf-8")
        self.assertIn('source_encoding = "utf-8"', render_config(got))
