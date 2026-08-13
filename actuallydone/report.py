"""HTML 渲染：单文件、零外链、深浅色自适应，双击就能看。

不引 CSS 框架也不联网取字体——报告经常被丢进聊天窗口或压缩包传给别人，
任何外链都可能在对方那里加载不出来。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .model import SEVERITY_ORDER, DimResult

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",
  "Helvetica Neue",Arial,sans-serif; background:Canvas; color:CanvasText; }
.wrap { max-width:1120px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:17px; margin:32px 0 12px; padding-bottom:6px;
  border-bottom:1px solid color-mix(in srgb, CanvasText 15%, transparent); }
h3 { font-size:15px; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
.meta { color:color-mix(in srgb, CanvasText 55%, transparent); margin-bottom:24px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; }
.card { border:1px solid color-mix(in srgb, CanvasText 15%, transparent);
  border-radius:10px; padding:14px 16px; }
.card.total { border-width:2px; }
.card.off { opacity:.55; border-style:dashed; }
.card .k { font-size:12px; color:color-mix(in srgb, CanvasText 55%, transparent); }
.card .v { font-size:26px; font-weight:600; line-height:1.25; }
.card .s { font-size:12px; color:color-mix(in srgb, CanvasText 45%, transparent); }
.dim { border:1px solid color-mix(in srgb, CanvasText 15%, transparent);
  border-radius:10px; padding:16px 18px; margin-bottom:16px; }
.dim.off { opacity:.55; border-style:dashed; }
.desc { margin:0; color:color-mix(in srgb, CanvasText 65%, transparent); font-size:13px; }
.metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:10px; margin-bottom:14px; }
.m { border-left:2px solid color-mix(in srgb, CanvasText 18%, transparent); padding-left:10px; }
.m .k { font-size:12px; color:color-mix(in srgb, CanvasText 55%, transparent); }
.m .v { font-size:18px; font-weight:600; }
.m .s { font-size:11px; color:color-mix(in srgb, CanvasText 45%, transparent); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { text-align:left; padding:6px 8px; vertical-align:top;
  border-top:1px solid color-mix(in srgb, CanvasText 12%, transparent); }
th { font-weight:600; font-size:12px; color:color-mix(in srgb, CanvasText 55%, transparent); }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px;
  background:color-mix(in srgb, CanvasText 8%, transparent); padding:1px 5px; border-radius:4px; }
.badge { display:inline-block; font-size:11px; padding:1px 7px; border-radius:99px;
  border:1px solid currentColor; white-space:nowrap; }
.err { color:#d33; } .warn { color:#b80; } .tip { color:#69c; }
.score { margin-left:auto; font-size:13px; font-weight:600; }
.good { color:#2a7; } .warnv { color:#b80; } .bad { color:#d33; }
.muted { color:color-mix(in srgb, CanvasText 40%, transparent); }
ul.notes { margin:12px 0 0; padding-left:18px; font-size:12.5px;
  color:color-mix(in srgb, CanvasText 65%, transparent); }
"""

READING = """
<li><b>总分只按本轮真跑过的维度加权</b>。跳过维度不会让分数变好看，卡片会灰显成「未评估」——
    否则 <code>--only skills</code> 就能刷出满分，那正是这套东西要防的事。</li>
<li><b>测试维度默认读最新门禁回执</b>，不重跑。回执与当前代码的树哈希不一致时判为过期，
    因为那份数据证明的是另一份代码。要重跑加 <code>--all</code>。</li>
<li><b>需求覆盖率低不扣分</b>：没做的需求不等于项目不健康。真正的偏离是「失联需求」——
    台账里标了已做，但绑定的表/路由/用例已经不存在了。</li>
<li><b>一致性分两类</b>：两份都自称权威全量的文件必须完全一致（代码质量维度）；
    文档自述是选摘的只查幻影，即「写了但代码里没有」，不要求反向全覆盖（AI 物料维度）。</li>
<li><b>顶部那行证据强度，管着上面所有数字的可信度</b>。「自述」是指这些结果由本地这台机器
    自己跑、自己记，能写文件的人就能改；「判据已锁」是指门禁有多严这件事有基线可对；
    「回执链完整」是指回执自哈希与链头对得上。要更硬的证据，得让一个 Agent 无权写入的
    执行者（CI）来跑。</li>
"""


def esc(s) -> str:
    return html.escape(str(s))


def tone_of(score: int) -> str:
    return "good" if score >= 85 else "warnv" if score >= 60 else "bad"


def render(results: list[DimResult], out: Path, total: int, ran_keys: list[str],
           dims, project: str, evidence: str = "") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_key = {d.key: d for d in dims}
    cls_of = {"错误": "err", "警告": "warn", "提示": "tip"}
    all_f = sorted(((r, f) for r in results for f in r.findings),
                   key=lambda t: (SEVERITY_ORDER[t[1].severity], t[0].key))
    n_err = sum(1 for _, f in all_f if f.severity == "错误")
    n_warn = sum(1 for _, f in all_f if f.severity == "警告")
    n_tip = sum(1 for _, f in all_f if f.severity == "提示")

    def badge(sev: str) -> str:
        return f'<span class="badge {cls_of[sev]}">{sev}</span>'

    cards = [f"""
      <div class="card total">
        <div class="k">总分</div><div class="v {tone_of(total)}">{total}</div>
        <div class="s">按本轮真跑过的 {len(ran_keys)}/{len(dims)} 个维度加权</div>
      </div>"""]
    for r in results:
        if not r.ran:
            cards.append(f"""
      <div class="card off">
        <div class="k">{esc(r.title)}</div><div class="v muted">未评估</div>
        <div class="s">{esc(r.why_skipped)}</div>
      </div>""")
            continue
        cards.append(f"""
      <div class="card">
        <div class="k">{esc(r.title)} · 权重 {by_key[r.key].weight}</div>
        <div class="v {tone_of(r.score)}">{r.score}</div>
        <div class="s">{r.errors} 错误 / {r.warnings} 警告 · {r.seconds}s</div>
      </div>""")

    blocks = []
    for r in results:
        if not r.ran:
            blocks.append(f"""
    <section class="dim off">
      <h3>{esc(r.title)} <span class="badge tip">本轮未评估</span></h3>
      <p class="desc">{esc(r.why_skipped)}</p>
    </section>""")
            continue
        metrics = "".join(f"""
        <div class="m"><div class="k">{esc(m.label)}</div>
        <div class="v {m.tone}">{esc(m.value)}</div>
        <div class="s">{esc(m.sub)}</div></div>""" for m in r.metrics)
        rows = "".join(
            f"<tr><td>{badge(f.severity)}</td><td><code>{esc(f.where)}</code></td>"
            f"<td>{esc(f.message)}</td></tr>"
            for f in sorted(r.findings, key=lambda x: SEVERITY_ORDER[x.severity])
        ) or "<tr><td colspan='3' class='muted'>没有发现问题</td></tr>"
        notes = "".join(f"<li>{esc(n)}</li>" for n in r.notes)
        blocks.append(f"""
    <section class="dim">
      <h3>{esc(r.title)}<span class="score {tone_of(r.score)}">{r.score}</span></h3>
      <div class="metrics">{metrics}</div>
      <table><thead><tr><th>级别</th><th>位置</th><th>说明</th></tr></thead>
        <tbody>{rows}</tbody></table>
      <ul class="notes">{notes}</ul>
    </section>""")

    rows_all = "".join(
        f"<tr><td>{badge(f.severity)}</td><td>{esc(r.title)}</td>"
        f"<td><code>{esc(f.where)}</code></td><td>{esc(f.message)}</td></tr>"
        for r, f in all_f) or "<tr><td colspan='4' class='muted'>全部检查通过</td></tr>"

    out.write_text(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(project)} 健康度 · {now}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>{esc(project)} · 健康度</h1>
<div class="meta">生成于 {now} · 本轮跑了 {esc('、'.join(ran_keys))} ·
  由 ActuallyDone 产出，每次运行覆盖本文件<br>
  {esc(evidence) if evidence else '证据强度：未知（还没有回执）'}</div>
<div class="cards">{''.join(cards)}</div>

<h2>逐维度</h2>
{''.join(blocks)}

<h2>问题汇总（{n_err} 错误 / {n_warn} 警告 / {n_tip} 提示）</h2>
<table><thead><tr><th>级别</th><th>维度</th><th>位置</th><th>说明</th></tr></thead>
<tbody>{rows_all}</tbody></table>

<h2>判读</h2>
<ul>{READING}</ul>
</div></body></html>
""", encoding="utf-8")
