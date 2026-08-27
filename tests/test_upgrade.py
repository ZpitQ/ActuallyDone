"""upgrade：版本比较、安装方式识别、git 安全检查。"""

from __future__ import annotations

from pathlib import Path

from actuallydone import __version__
from actuallydone.cli import build_parser
from actuallydone.upgrade import (git_blockers, install_argv, install_mode,
                                  parse_version, repo_root)
from tests.helpers import ProjectCase


class TestUpgradeCli(ProjectCase):
    def test_upgrade不依赖adone_toml(self):
        ap = build_parser()
        args = ap.parse_args(["upgrade", "--check"])
        self.assertTrue(args.check)
        self.assertEqual(args.func.__name__, "cmd_upgrade")


class TestParseVersion(ProjectCase):
    def test_容v前缀与预发布后缀(self):
        self.assertEqual(parse_version("v1.2.0"), (1, 2, 0))
        self.assertEqual(parse_version("1.2.0-rc.1"), (1, 2, 0))
        self.assertTrue(parse_version("1.2.0") > parse_version("1.1.0"))
        self.assertTrue(parse_version("1.10.0") > parse_version("1.9.0"))

    def test_两个版本号来源必须一致(self):
        root = Path(__file__).resolve().parent.parent
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        import re
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), __version__)


class TestInstallMode(ProjectCase):
    def test_pipx优先于site_packages(self):
        fake = (self.root / "pipx/venvs/actuallydone/lib/python3.13/"
                "site-packages/actuallydone/upgrade.py")
        fake.parent.mkdir(parents=True)
        fake.write_text("", encoding="utf-8")
        self.assertEqual(install_mode(fake), "pipx")

    def test_site_packages是pip(self):
        fake = self.root / "lib/python3.13/site-packages/actuallydone/upgrade.py"
        fake.parent.mkdir(parents=True)
        fake.write_text("", encoding="utf-8")
        self.assertEqual(install_mode(fake), "pip")

    def test_带git目录是git工作树(self):
        fake = self.root / "actuallydone/upgrade.py"
        fake.parent.mkdir(parents=True)
        fake.write_text("", encoding="utf-8")
        (self.root / ".git").mkdir()
        self.assertEqual(install_mode(fake), "git")

    def test_pipx命令用pipx不是裸pip(self):
        argv = install_argv("pipx", "v1.3.0")
        self.assertEqual(argv[0], "pipx")
        self.assertIn("--force", argv)

    def test_pip命令走当前解释器的模块(self):
        argv = install_argv("pip", "v1.3.0")
        self.assertEqual(argv[1:3], ["-m", "pip"])
        self.assertIn("--upgrade", argv)

    def test_repo_root是包的上一级(self):
        self.assertEqual(repo_root().name, "ActuallyDone")


class TestGitBlockers(ProjectCase):
    def test_脏工作树被拦住(self):
        import subprocess
        subprocess.run(["git", "init"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.root,
                       capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.root,
                       capture_output=True)
        (self.root / "a.txt").write_text("x", encoding="utf-8")
        problems = git_blockers(self.root)
        self.assertTrue(any("不干净" in p for p in problems))
