"""步骤执行：实时输出、超时、杀进程树。卡死不能再长得像在跑。"""

from __future__ import annotations

import os
import sys
import time
from io import StringIO
from contextlib import redirect_stdout

from actuallydone import gate
from tests.helpers import ProjectCase


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class TestRunStepStream(ProjectCase):
    def test_步骤还在跑时已经有输出(self):
        cfg = self.config()
        buf = StringIO()
        with redirect_stdout(buf):
            st = gate.run_step(cfg, {
                "name": "stream", "cwd": ".",
                "argv": _py("import sys,time; sys.stdout.write('HELLO\\n'); "
                            "sys.stdout.flush(); time.sleep(0.3); "
                            "sys.stdout.write('BYE\\n')"),
            })
        self.assertTrue(st.ok)
        self.assertIn("HELLO", st.stdout)
        self.assertIn("BYE", st.stdout)
        self.assertIn("HELLO", buf.getvalue())

    def test_stderr合流进stdout(self):
        cfg = self.config()
        with redirect_stdout(StringIO()):
            st = gate.run_step(cfg, {
                "name": "merge", "cwd": ".",
                "argv": _py("import sys; sys.stderr.write('ERR\\n'); "
                            "sys.stdout.write('OUT\\n')"),
            })
        self.assertIn("ERR", st.stdout)
        self.assertIn("OUT", st.stdout)

    def test_超时步骤失败且记下(self):
        cfg = self.config()
        t0 = time.time()
        with redirect_stdout(StringIO()):
            st = gate.run_step(cfg, {
                "name": "sleep", "cwd": ".",
                "timeout_seconds": 1,
                "argv": _py("import time; time.sleep(30)"),
            })
        self.assertLess(time.time() - t0, 8)
        self.assertTrue(st.timed_out)
        self.assertFalse(st.ok)
        self.assertNotEqual(st.exit_code, 0)
        self.assertIn("超时", st.note)
        self.assertTrue(st.as_receipt().get("timed_out"))

    def test_卡死按无输出中断(self):
        cfg = self.config()
        with redirect_stdout(StringIO()):
            st = gate.run_step(cfg, {
                "name": "stall", "cwd": ".",
                "stall_seconds": 1,
                "argv": _py("import sys,time; sys.stdout.write('once\\n'); "
                            "sys.stdout.flush(); time.sleep(30)"),
            })
        self.assertTrue(st.timed_out)
        self.assertFalse(st.ok)
        self.assertIn("没有新输出", st.note)
        self.assertIn("once", st.stdout)

    def test_超时不会被格式化步骤判成通过(self):
        cfg = self.config()
        st = gate.Step(name="fmt", cwd=".", argv=["x"])
        st.exit_code, st.ok, st.timed_out, st.stdout = 124, False, True, ""
        st.note = "超时 1 秒被中断"
        gate.judge_step(cfg, {"kind": "fmt"}, st)
        self.assertFalse(st.ok)
        self.assertIn("超时", st.note)

    def test_静默超时会打心跳(self):
        old = gate.HEARTBEAT_SECONDS
        gate.HEARTBEAT_SECONDS = 0.3
        try:
            buf = StringIO()
            with redirect_stdout(buf):
                gate.run_step(self.config(), {
                    "name": "beat", "cwd": ".",
                    "timeout_seconds": 1.2,
                    "argv": _py("import time; time.sleep(1.0)"),
                })
            self.assertIn("没有新输出", buf.getvalue())
        finally:
            gate.HEARTBEAT_SECONDS = old

    def test_杀树后子进程也没了(self):
        pidfile = self.root / "child.pid"
        script = (
            "import os,sys,time,subprocess\n"
            f"child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
            f"open(r'{pidfile}','w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        cfg = self.config()
        with redirect_stdout(StringIO()):
            st = gate.run_step(cfg, {
                "name": "tree", "cwd": ".",
                "timeout_seconds": 1,
                "argv": _py(script),
            })
        self.assertTrue(st.timed_out)
        self.assertTrue(pidfile.is_file(), "子进程还没来得及写 pid")
        child = int(pidfile.read_text())
        dead = False
        for _ in range(40):
            try:
                os.kill(child, 0)
            except OSError:
                dead = True
                break
            time.sleep(0.1)
        self.assertTrue(dead, f"子进程 {child} 还活着，杀树没生效")
