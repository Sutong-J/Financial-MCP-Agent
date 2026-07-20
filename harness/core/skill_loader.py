"""
Skill 加载器 - 从 skills/{agent_name}/SKILL.md 加载分析指令
支持渐进式披露（core → execution → remediation）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

USER_TEMPLATE_MARKER = "## 用户请求模板"
DISCLOSURE_LEVELS = ("core", "execution", "remediation")
DISCLOSE_MARKER = re.compile(r"<!--\s*disclose:\s*(\w+)\s*-->", re.IGNORECASE)

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

REQUIRED_VARIABLES = {
    "fundamental_agent": ["company_name", "stock_code", "current_time_info", "current_date"],
    "technical_agent": ["company_name", "stock_code", "current_time_info", "current_date"],
    "value_agent": ["company_name", "stock_code", "current_time_info", "current_date"],
    "news_agent": ["company_name", "stock_code", "current_time_info", "current_date"],
    "summary_agent": [
        "company_name", "stock_code", "current_time_info", "current_date",
        "user_query", "fundamental_analysis", "technical_analysis",
        "value_analysis", "news_analysis", "errors_section",
    ],
    "follow_up_agent": [
        "company_name", "stock_code", "current_time_info", "current_date",
        "user_query", "chat_history", "session_summary", "retrieval_mode",
        "retrieved_context", "report_fallback",
    ],
}

_skill_cache: dict[str, Skill] = {}


@dataclass
class Skill:
    name: str
    description: str
    version: str
    system_prompt: str
    user_prompt_template: str
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 6000
    max_retries: int = 1
    verification: dict[str, Any] = field(default_factory=dict)
    raw_body: str = ""
    disclosure_sections: dict[str, str] = field(default_factory=dict)

    def build_system_prompt(self, attempt: int = 0) -> str:
        """按渐进式披露层级组装 system prompt。

        - attempt == 0: core + execution
        - attempt > 0:  core + execution + remediation（验证失败重试时展开）
        """
        if self.disclosure_sections:
            return join_disclosure_sections(self.disclosure_sections, attempt)
        return self.system_prompt

    def disclosed_level_names(self, attempt: int = 0) -> list[str]:
        """返回当前 attempt 已披露的层级名称。"""
        if not self.disclosure_sections:
            return ["legacy"]
        levels: list[str] = []
        if self.disclosure_sections.get("core"):
            levels.append("core")
        if self.disclosure_sections.get("execution"):
            levels.append("execution")
        if attempt > 0 and self.disclosure_sections.get("remediation"):
            levels.append("remediation")
        return levels

    def render(self, variables: dict[str, Any]) -> Skill:
        """渲染模板变量，返回新的 Skill 实例。"""
        rendered_sections = {
            key: render_template(content, variables)
            for key, content in self.disclosure_sections.items()
        }
        rendered_user = render_template(self.user_prompt_template, variables)
        return Skill(
            name=self.name,
            description=self.description,
            version=self.version,
            system_prompt=join_disclosure_sections(rendered_sections, attempt=0),
            user_prompt_template=rendered_user,
            allowed_tools=self.allowed_tools,
            forbidden_tools=self.forbidden_tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_retries=self.max_retries,
            verification=self.verification,
            raw_body=self.raw_body,
            disclosure_sections=rendered_sections,
        )


def join_disclosure_sections(sections: dict[str, str], attempt: int) -> str:
    """拼接披露层级内容为 system prompt。"""
    parts: list[str] = []
    if sections.get("core"):
        parts.append(sections["core"])
    if sections.get("execution"):
        parts.append(sections["execution"])
    if attempt > 0 and sections.get("remediation"):
        parts.append(sections["remediation"])
    return "\n\n".join(parts).strip()


def render_template(template: str, variables: dict[str, Any]) -> str:
    """将 {key} 占位符替换为 variables 中的值。"""
    if not template:
        return ""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    remaining = re.findall(r"\{(\w+)\}", result)
    if remaining:
        missing = ", ".join(sorted(set(remaining)))
        raise ValueError(f"Skill 模板存在未替换变量: {missing}")
    return result


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content.strip()
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content.strip()
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return meta, body


def _split_prompt_sections(body: str) -> tuple[str, str]:
    if USER_TEMPLATE_MARKER in body:
        idx = body.index(USER_TEMPLATE_MARKER)
        system_body = body[:idx].strip()
        user_template = body[idx + len(USER_TEMPLATE_MARKER):].strip()
        return system_body, user_template
    return body.strip(), ""


def _parse_disclosure_sections(body: str) -> dict[str, str]:
    """解析 <!-- disclose: level --> 标记的分层内容。"""
    valid = set(DISCLOSURE_LEVELS)
    buckets: dict[str, list[str]] = {level: [] for level in DISCLOSURE_LEVELS}

    matches = list(DISCLOSE_MARKER.finditer(body))
    if not matches:
        if body.strip():
            buckets["core"].append(body.strip())
        return {k: "\n\n".join(v).strip() for k, v in buckets.items() if v}

    prefix = body[: matches[0].start()].strip()
    if prefix:
        buckets["core"].append(prefix)

    for index, match in enumerate(matches):
        level = match.group(1).lower()
        if level not in valid:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if chunk:
            buckets[level].append(chunk)

    return {k: "\n\n".join(v).strip() for k, v in buckets.items() if v}


def load_skill(agent_name: str, *, use_cache: bool = True) -> Skill:
    """加载指定 Agent 的 Skill 文件。"""
    if use_cache and agent_name in _skill_cache:
        return _skill_cache[agent_name]

    skill_path = SKILLS_DIR / agent_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill 文件不存在: {skill_path}")

    content = skill_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(content)
    system_body, user_template = _split_prompt_sections(body)
    disclosure_sections = _parse_disclosure_sections(system_body)

    skill = Skill(
        name=meta.get("name", agent_name),
        description=meta.get("description", ""),
        version=str(meta.get("version", "1.0")),
        system_prompt=join_disclosure_sections(disclosure_sections, attempt=0),
        user_prompt_template=user_template,
        allowed_tools=list(meta.get("allowed_tools") or []),
        forbidden_tools=list(meta.get("forbidden_tools") or []),
        temperature=float(meta.get("temperature", 0.3)),
        max_tokens=int(meta.get("max_tokens", 6000)),
        max_retries=int(meta.get("max_retries", 1)),
        verification=dict(meta.get("verification") or {}),
        raw_body=body,
        disclosure_sections=disclosure_sections,
    )

    if use_cache:
        _skill_cache[agent_name] = skill
    return skill


def render_skill(skill: Skill, variables: dict[str, Any]) -> Skill:
    """校验必需变量并渲染 Skill。"""
    required = REQUIRED_VARIABLES.get(skill.name, [])
    missing = [v for v in required if v not in variables]
    if missing:
        raise ValueError(f"Skill '{skill.name}' 缺少必需变量: {', '.join(missing)}")
    return skill.render(variables)


def clear_skill_cache() -> None:
    """清空 Skill 缓存（测试或热更新时使用）。"""
    _skill_cache.clear()
