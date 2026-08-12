"""维度：业务不变量探针。

单测证明函数对，探针证明**跑起来的系统**里那条业务规则还成立。
它可能要服务在跑、可能会写数据，所以默认不跑，`--with-probes` 才执行。

一个关键区分：「探针跑不起来」是警告，「不变量被破坏」才是错误。
混为一谈会让人以为业务出了问题，实际只是服务没起。
"""

from __future__ import annotations

import re
import subprocess
import time

from ..model import DimResult, Metric

DEFAULT_UNREACHABLE = ("Connection refused", "URLError", "Errno 61", "Max retries",
                       "connection refused", "ECONNREFUSED")


def run(ctx) -> DimResult:
    cfg = ctx.cfg
    res = DimResult("probes", "业务不变量")
    specs = cfg.get("probe", []) or []
    if not specs:
        return res.skip("没配任何 [[probe]]：不变量探针要自己写，工具不猜业务规则")
    if not ctx.with_probes:
        return res.skip("默认不跑（可能要服务在跑、可能会写数据），加 --with-probes 执行")

    total_pass = total_fail = 0
    for spec in specs:
        name = spec.get("name") or " ".join(spec.get("argv", []))[:30]
        argv = spec.get("argv") or []
        if not argv:
            res.add("警告", "adone.toml", f"探针「{name}」没有 argv")
            continue
        t0 = time.time()
        try:
            proc = subprocess.run(argv, cwd=cfg.root / spec.get("cwd", "."),
                                  capture_output=True, text=True,
                                  timeout=float(spec.get("timeout", 600)))
        except subprocess.TimeoutExpired:
            res.add("警告", name, "探针超时，没跑完——这不代表不变量出问题")
            continue
        except FileNotFoundError as e:
            res.add("警告", name, f"命令不存在：{e.filename}")
            continue
        out = proc.stdout + proc.stderr
        secs = round(time.time() - t0, 1)

        pass_re = spec.get("pass_pattern", r"PASS")
        fail_re = spec.get("fail_pattern", r"FAIL")
        n_pass = len(re.findall(pass_re, out))
        n_fail = len(re.findall(fail_re, out))
        marks = spec.get("unreachable_marks") or list(DEFAULT_UNREACHABLE)
        unreachable = any(k in out for k in marks)

        if unreachable:
            res.add("警告", name,
                    "依赖的服务连不上，探针没跑成——这不代表不变量被破坏，"
                    "先把服务起起来再看")
        elif n_fail:
            for ln in out.splitlines():
                if re.search(fail_re, ln):
                    res.add("错误", name, ln.strip()[:200])
        elif proc.returncode != 0:
            res.add("错误", name,
                    f"探针退出码 {proc.returncode}，尾巴：{out.strip()[-200:]}")
        total_pass += n_pass
        total_fail += n_fail
        res.metrics.append(Metric(
            name, "未跑成" if unreachable else f"{n_pass} 通过",
            "服务不可达" if unreachable else f"{n_fail} 失败 · {secs}s",
            "warnv" if unreachable else "bad" if n_fail else "good"))

    res.notes.append(f"共 {len(specs)} 个探针，{total_pass} 条断言通过、{total_fail} 条失败。"
                     f"探针要自己写：它编码的是本项目的业务规则，通用工具替不了。")
    return res
