"""技能沉淀采集：扫技能目录，认定事实，不判分也不排版。

技能腐坏的主要形态是**引用的代码路径与行号失效**——代码改了，技能还停在旧位置，
于是 Agent 被一份看起来权威、实际过期的说明带偏。这里把它当错误级来抓。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# SKILL.md 体积阈值：软阈值是经验值，硬阈值来自 Cursor 官方建议
SOFT_LINE_LIMIT = 120
HARD_LINE_LIMIT = 500
DESC_MAX = 1024
NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MD_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")
# description 里表示「什么时候用」的信号词，中英文都收
WHEN_HINTS = ("时使用", "时也使用", "使用", "调用时", "要求", "when ", "use when")


@dataclass
class Issue:
    severity: str
    skill: str
    where: str
    message: str


@dataclass
class SkillReport:
    name: str
    dir_name: str
    front: dict[str, str]
    skill_lines: int
    skill_tokens: int
    refs: list[tuple[str, int]] = field(default_factory=list)
    scripts: list[tuple[str, bool]] = field(default_factory=list)
    orphan_refs: list[str] = field(default_factory=list)
    code_refs_ok: int = 0
    code_refs_bad: list[str] = field(default_factory=list)
    invariants: set[str] = field(default_factory=set)
    dup_lines: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def auto_invoke(self) -> bool:
        return self.front.get("disable-model-invocation", "").strip().lower() != "true"

    @property
    def score(self) -> int:
        penalty = sum(15 if i.severity == "错误" else 5 if i.severity == "警告" else 0
                      for i in self.issues)
        return max(0, 100 - penalty)


def est_tokens(text: str) -> int:
    """粗略估算 token：CJK 约 1.2 个/字，其余按 4 字符 1 个。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.2 + (len(text) - cjk) / 4)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block, body = text[3:end], text[end + 4:]
    front: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([a-zA-Z-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            front[key] = m.group(2).strip()
        elif key:  # YAML 折叠块的续行
            front[key] += " " + line.strip()
    return front, body


def code_path_re(root: Path) -> re.Pattern:
    """按仓库实际的顶层目录拼正则，避免把 markdown 里的普通词当路径。"""
    tops = sorted(d.name for d in root.iterdir()
                  if d.is_dir() and not d.name.startswith("."))
    if not tops:
        tops = ["src"]
    alt = "|".join(re.escape(t) for t in tops)
    return re.compile(
        rf"(?<![\w/.])((?:{alt})/[\w./-]+"
        rf"\.(?:go|ts|tsx|vue|sql|md|py|sh|rs|java|kt|yaml|yml|mmd|json))(?::(\d+))?")


def doc_lines(path: Path | None) -> set[str]:
    """权威文档里的长行，用来发现技能里的逐字复制（违反单一事实来源）。"""
    if not path or not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if len(ln.strip()) >= 30}


def check_skill(d: Path, root: Path, agent_lines: set[str],
                invariant_re: re.Pattern | None = None) -> SkillReport:
    skill_md = d / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    front, body = parse_frontmatter(text)
    rep = SkillReport(
        name=front.get("name", d.name),
        dir_name=d.name,
        front=front,
        skill_lines=len(text.splitlines()),
        skill_tokens=est_tokens(text),
    )
    add = rep.issues.append
    path_re = code_path_re(root)

    # --- frontmatter 合规 ---
    if not front.get("name"):
        add(Issue("错误", rep.name, "SKILL.md", "frontmatter 缺 name"))
    elif not NAME_RE.match(front["name"]):
        add(Issue("错误", rep.name, "SKILL.md",
                  f"name «{front['name']}» 不合规（只允许小写字母/数字/连字符，≤64 字符）"))
    elif front["name"] != d.name:
        add(Issue("警告", rep.name, "SKILL.md",
                  f"name «{front['name']}» 与目录名 «{d.name}» 不一致，检索时容易对不上"))

    desc = front.get("description", "")
    if not desc:
        add(Issue("错误", rep.name, "SKILL.md",
                  "frontmatter 缺 description，Agent 无从判断何时加载"))
    else:
        if len(desc) > DESC_MAX:
            add(Issue("错误", rep.name, "SKILL.md", f"description 超长（{len(desc)} > {DESC_MAX}）"))
        if len(desc) < 40:
            add(Issue("警告", rep.name, "SKILL.md", "description 过短，触发词不足容易漏触发"))
        if not any(h in desc for h in WHEN_HINTS):
            add(Issue("警告", rep.name, "SKILL.md",
                      "description 没写清「何时使用」，只有 WHAT 没有 WHEN"))

    # --- 体积 ---
    if rep.skill_lines > HARD_LINE_LIMIT:
        add(Issue("错误", rep.name, "SKILL.md",
                  f"{rep.skill_lines} 行，超过官方硬阈值 {HARD_LINE_LIMIT} 行"))
    elif rep.skill_lines > SOFT_LINE_LIMIT:
        add(Issue("警告", rep.name, "SKILL.md",
                  f"{rep.skill_lines} 行，超过软阈值 {SOFT_LINE_LIMIT} 行，考虑拆到 references/"))

    # --- references 与链接 ---
    ref_dir = d / "references"
    ref_files = sorted(p for p in ref_dir.glob("*.md")) if ref_dir.is_dir() else []
    rep.refs = [(p.name, len(p.read_text(encoding="utf-8").splitlines())) for p in ref_files]

    linked: set[str] = set()
    for target in MD_LINK_RE.findall(body):
        if target.startswith(("http://", "https://")):
            continue
        linked.add(target)
        if not (d / target).exists():
            add(Issue("错误", rep.name, "SKILL.md", f"断链：引用了不存在的 {target}"))
    for p in ref_files:
        if f"references/{p.name}" not in linked:
            rep.orphan_refs.append(p.name)
            add(Issue("警告", rep.name, f"references/{p.name}",
                      "没有被 SKILL.md 引用，渐进式加载够不到它"))

    # 引用只做一层深：references 里不该再指向别的 references
    for p in ref_files:
        for target in MD_LINK_RE.findall(p.read_text(encoding="utf-8")):
            if target.startswith("references/"):
                add(Issue("警告", rep.name, f"references/{p.name}",
                          f"二层引用 {target}，深层引用可能只被读到一半"))

    # --- scripts ---
    script_dir = d / "scripts"
    if script_dir.is_dir():
        for p in sorted(script_dir.iterdir()):
            if not p.is_file():
                continue
            executable = bool(p.stat().st_mode & 0o111)
            rep.scripts.append((p.name, executable))
            if not executable:
                add(Issue("警告", rep.name, f"scripts/{p.name}", "没有可执行位（chmod +x）"))
            if p.name not in text:
                add(Issue("警告", rep.name, f"scripts/{p.name}",
                          "SKILL.md 没提到这个脚本，Agent 不会知道要跑它"))

    # --- 引用的仓库代码路径是否还在 ---
    for p in [skill_md, *ref_files]:
        content = p.read_text(encoding="utf-8")
        rel = p.relative_to(d)
        for path_str, lineno in path_re.findall(content):
            target = next((c for c in (root / path_str, d / path_str) if c.exists()),
                          root / path_str)
            if not target.exists():
                rep.code_refs_bad.append(f"{rel}: {path_str}（文件不存在）")
                add(Issue("错误", rep.name, str(rel), f"引用的代码路径已不存在：{path_str}"))
                continue
            if lineno:
                total = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
                if int(lineno) > total:
                    rep.code_refs_bad.append(f"{rel}: {path_str}:{lineno}（只有 {total} 行）")
                    add(Issue("错误", rep.name, str(rel),
                              f"行号越界：{path_str}:{lineno}，该文件只有 {total} 行"))
                    continue
            rep.code_refs_ok += 1

        if invariant_re is not None:
            rep.invariants |= set(invariant_re.findall(content))

        # 重复留痕只看正文：围栏里的命令行本来就该照抄，不算违反单一事实来源
        in_fence = False
        for ln in content.splitlines():
            s = ln.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and len(s) >= 30 and s in agent_lines:
                rep.dup_lines.append(f"{rel}: {s[:60]}…")

    for dup in rep.dup_lines:
        add(Issue("提示", rep.name, dup.split(":")[0],
                  "与权威文档逐字重复，违反「单一事实来源」，应改为链回"))

    return rep


def scan_skills(skills_dir: Path, root: Path, agent_doc: Path | None = None,
                invariant_pattern: str = "") -> list[SkillReport]:
    if not skills_dir.is_dir():
        return []
    dirs = sorted(d for d in skills_dir.iterdir()
                  if d.is_dir() and (d / "SKILL.md").exists())
    lines = doc_lines(agent_doc)
    inv = re.compile(invariant_pattern) if invariant_pattern else None
    return [check_skill(d, root, lines, inv) for d in dirs]
