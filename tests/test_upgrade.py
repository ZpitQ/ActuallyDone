"""upgrade：版本比较、安装方式识别、git 安全检查。"""

from __future__ import annotations

import os
from argparse import Namespace
from io import StringIO
from pathlib import Path
from contextlib import redirect_stdout

from actuallydone import __version__
from actuallydone.cli import build_parser
from actuallydone.upgrade import (classify_entry, git_blockers, install_argv,
                                  install_mode, maybe_offer_upgrade,
                                  parse_version, read_cache, repo_root,
                                  skip_nudge, write_cache)
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

    def test_PATH上的pipx入口优先于当前源码(self):
        entry = self.root / "adone"
        entry.write_text(
            "#!/Users/x/.local/pipx/venvs/actuallydone/bin/python\n"
            "from actuallydone.cli import main\n",
            encoding="utf-8")
        self.assertEqual(classify_entry(entry), "pipx")

    def test_仓库内bin_adone认成git(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        entry = bindir / "adone"
        (self.root / "actuallydone").mkdir()
        (self.root / "actuallydone" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / ".git").mkdir()
        entry.write_text("#!/usr/bin/env python3\nfrom actuallydone.cli import main\n",
                         encoding="utf-8")
        self.assertEqual(classify_entry(entry), "git")

    def test_Windows的adone_exe也认成git(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        entry = bindir / "adone.exe"
        (self.root / "actuallydone").mkdir()
        (self.root / "actuallydone" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / ".git").mkdir()
        entry.write_bytes(b"MZ")
        self.assertEqual(classify_entry(entry), "git")


class TestNudge(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.cache = self.root / "update-check.json"
        self.old_cache = os.environ.get("ADONE_UPDATE_CACHE")
        self.old_off = os.environ.get("ADONE_NO_UPDATE_CHECK")
        os.environ["ADONE_UPDATE_CACHE"] = str(self.cache)
        os.environ.pop("ADONE_NO_UPDATE_CHECK", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self.old_cache is None:
            os.environ.pop("ADONE_UPDATE_CACHE", None)
        else:
            os.environ["ADONE_UPDATE_CACHE"] = self.old_cache
        if self.old_off is None:
            os.environ.pop("ADONE_NO_UPDATE_CHECK", None)
        else:
            os.environ["ADONE_NO_UPDATE_CHECK"] = self.old_off

    def _args(self, **over) -> Namespace:
        base = dict(cmd="doctor", json=False)
        base.update(over)
        return Namespace(**base)

    def test_钩子和json和显式关掉都不问(self):
        os.environ["ADONE_NO_UPDATE_CHECK"] = "1"
        self.assertTrue(skip_nudge(self._args()))
        os.environ.pop("ADONE_NO_UPDATE_CHECK")
        self.assertTrue(skip_nudge(self._args(cmd="hook")))
        self.assertTrue(skip_nudge(self._args(cmd="upgrade")))
        self.assertTrue(skip_nudge(self._args(json=True)))
        called = []
        rc = maybe_offer_upgrade(self._args(cmd="hook"),
                                 peek=lambda: called.append("peek") or ("v9", "9.9.9"),
                                 ask=lambda *_: called.append("ask") or True)
        self.assertIsNone(rc)
        self.assertEqual(called, [])

    def test_缓存里已是最新就不再联网(self):
        write_cache({"checked_at": 1e18, "remote_ver": __version__,
                     "remote_ref": "v" + __version__})
        called = []
        rc = maybe_offer_upgrade(self._args(), peek=lambda: called.append("peek") or (None, None),
                                 ask=lambda *_: called.append("ask") or True, force=True)
        self.assertIsNone(rc)
        self.assertEqual(called, [])

    def test_有新版用户拒绝就继续原命令(self):
        write_cache({"checked_at": 1, "remote_ver": "9.9.9", "remote_ref": "v9.9.9"})
        asked = []
        rc = maybe_offer_upgrade(
            self._args(), peek=lambda: (_ for _ in ()).throw(AssertionError("不该联网")),
            ask=lambda loc, rem: asked.append((loc, rem)) or False,
            now=2, force=True)
        self.assertIsNone(rc)
        self.assertEqual(asked, [(__version__, "9.9.9")])

    def test_有新版用户同意才升级并中止原命令(self):
        write_cache({"checked_at": 1, "remote_ver": "9.9.9", "remote_ref": "v9.9.9"})
        with redirect_stdout(StringIO()):
            rc = maybe_offer_upgrade(
                self._args(),
                peek=lambda: (_ for _ in ()).throw(AssertionError("不该联网")),
                ask=lambda *_: True,
                upgrade=lambda: 0,
                now=2, force=True)
        self.assertEqual(rc, 0)

    def test_缓存过期才去探远端(self):
        write_cache({"checked_at": 1, "remote_ver": __version__, "remote_ref": "v1"})
        peeked = []
        rc = maybe_offer_upgrade(
            self._args(),
            peek=lambda: peeked.append(1) or ("v9.9.9", "9.9.9"),
            ask=lambda *_: False,
            now=1 + 13 * 3600, force=True)
        self.assertIsNone(rc)
        self.assertEqual(peeked, [1])
        self.assertEqual(read_cache().get("remote_ver"), "9.9.9")

    def test_探不到就静默放过(self):
        rc = maybe_offer_upgrade(self._args(), peek=lambda: (None, None),
                                 ask=lambda *_: True, now=1, force=True)
        self.assertIsNone(rc)
        self.assertFalse(self.cache.exists())


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
