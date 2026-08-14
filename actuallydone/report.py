"""HTML 渲染：单文件、零外链、深浅色自适应，双击就能看。

不引 CSS 框架也不联网取字体——报告经常被丢进聊天窗口或压缩包传给别人，
任何外链都可能在对方那里加载不出来。
"""

from __future__ import annotations

import html
import subprocess
import sys
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

AUDIT_READING = """
<li><b>复核只有两种结论</b>：通过，或者未通过加一张问题清单。
    「独立复核通过」只证明这份证据自洽，且复核者核到了报告里写明的那一层——
    不替实现者宣布完成。</li>
<li><b>核到哪一层就说哪一层</b>。只读证据、抽 N 条当场真跑、全量重跑是三档不同的强度，
    写成同一句话等于把最弱的一档冒充最强的。</li>
<li><b>本机复核不是不可伪造</b>。复核者与实现者同一台机器、同一套写权限。
    铁了心可以重算回执链并改基线。不要把「独立复核通过」写成「不可能造假」。
    真正不可伪造需要一个 Agent 无权写入的执行者（CI）。</li>
<li><b>复核者不覆盖被审证据</b>。结论只落 <code>audit.json</code> / <code>audit.html</code>
    / <code>audits/</code>，不碰 <code>latest.json</code> 与证据链。</li>
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


def open_report(path: Path) -> None:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, str(path)], check=False)


def _short(h) -> str:
    return (str(h)[:12] if h else "") or "无"


def _audit_how(v: dict) -> str:
    if v.get("mode") == "rerun":
        return "全量重跑核对"
    asked = (v.get("spotcheck") or {}).get("asked") or 0
    notes = (v.get("spotcheck") or {}).get("notes") or []
    if any("抽查真跑" in n for n in notes):
        return f"抽 {asked} 条当场真跑"
    if asked:
        return f"抽查 {asked} 条（未评估或未跑成）"
    return "只读证据核对"


def render_audit(verdict: dict, out: Path, project: str) -> None:
    """把一份审计结论渲成可离线双击打开的 HTML。不重跑检查。"""
    ok = bool(verdict.get("ok"))
    created = esc(verdict.get("created_at") or datetime.now().isoformat(timespec="seconds"))
    aud = verdict.get("audited_receipt") or {}
    tree = verdict.get("tree") or {}
    problems = list(verdict.get("problems") or [])
    details = list(verdict.get("details") or [])
    notes = list((verdict.get("spotcheck") or {}).get("notes") or [])
    evidence = esc(verdict.get("evidence_line") or "证据强度：未知")
    how = _audit_how(verdict)
    verdict_cls = "good" if ok else "bad"
    verdict_text = "通过" if ok else "未通过"
    headline = ("独立复核通过：这份交付的证据自洽"
                if ok else "独立复核未通过，实现者不能宣称完成")

    cards = f"""
      <div class="card total">
        <div class="k">判定</div><div class="v {verdict_cls}">{verdict_text}</div>
        <div class="s">{esc(how)}</div>
      </div>
      <div class="card">
        <div class="k">对照回执</div><div class="v">{esc(aud.get("id") or "无")}</div>
        <div class="s">自哈希 {_short(aud.get("self_hash"))}</div>
      </div>
      <div class="card">
        <div class="k">当前树</div><div class="v">{esc(_short(tree.get("hash")))}</div>
        <div class="s">{esc(tree.get("file_count") or 0)} 个文件</div>
      </div>
      <div class="card">
        <div class="k">审计 ID</div><div class="v">{esc(verdict.get("id") or "")}</div>
        <div class="s">自哈希 {_short(verdict.get("self_hash"))}</div>
      </div>"""

    detail_rows = "".join(
        f"<tr><td class='muted'>·</td><td>{esc(d)}</td></tr>" for d in details
    ) or "<tr><td colspan='2' class='muted'>没有明细</td></tr>"

    if problems:
        problem_rows = "".join(
            f"<tr><td><span class='badge err'>问题</span></td><td>{esc(p)}</td></tr>"
            for p in problems)
    else:
        problem_rows = "<tr><td colspan='2' class='muted'>空</td></tr>"

    note_rows = "".join(f"<li>{esc(n)}</li>" for n in notes) or "<li class='muted'>本次没有抽查记录</li>"

    rerun = verdict.get("rerun")
    rerun_block = ""
    if rerun:
        if rerun.get("error"):
            rerun_body = f"<p class='desc'>{esc(rerun['error'])}</p>"
        else:
            steps = rerun.get("steps") or []
            step_rows = "".join(
                f"<tr><td>{esc(s.get('name'))}</td>"
                f"<td class='{'good' if s.get('ok') else 'bad'}'>"
                f"{'通过' if s.get('ok') else '未通过'}</td></tr>"
                for s in steps
            ) or "<tr><td colspan='2' class='muted'>没有步骤记录</td></tr>"
            cov = (rerun.get("coverage") or {}).get("percent")
            rerun_body = f"""
      <div class="metrics">
        <div class="m"><div class="k">重跑结果</div>
        <div class="v {'good' if rerun.get('ok') else 'bad'}">{'通过' if rerun.get('ok') else '未通过'}</div>
        <div class="s">{esc(rerun.get('seconds') or 0)}s</div></div>
        <div class="m"><div class="k">覆盖率</div>
        <div class="v">{esc(cov) if cov is not None else '—'}</div>
        <div class="s">下限 {esc((rerun.get('coverage') or {}).get('threshold') or '—')}</div></div>
      </div>
      <table><thead><tr><th>步骤</th><th>结果</th></tr></thead>
        <tbody>{step_rows}</tbody></table>"""
        rerun_block = f"""
<h2>独立重跑</h2>
<section class="dim">{rerun_body}</section>"""

    out.write_text(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(project)} 独立复核 · {created}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>{esc(project)} · 独立复核</h1>
<div class="meta">审计 {esc(verdict.get("id") or "")} · 生成于 {created} ·
  由 ActuallyDone 产出，不覆盖实现者的回执与证据链<br>
  {evidence}</div>
<div class="cards">{cards}</div>

<h2>{esc(headline)}</h2>
<table><thead><tr><th></th><th>明细</th></tr></thead>
<tbody>{detail_rows}</tbody></table>

<h2>问题清单（{len(problems)}）</h2>
<table><thead><tr><th>级别</th><th>说明</th></tr></thead>
<tbody>{problem_rows}</tbody></table>

<h2>抽查</h2>
<ul class="notes">{note_rows}</ul>
{rerun_block}

<h2>判读</h2>
<ul>{AUDIT_READING}</ul>
</div></body></html>
""", encoding="utf-8")
