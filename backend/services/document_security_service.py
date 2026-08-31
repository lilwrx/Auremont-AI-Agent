"""Context-aware prompt-injection screening for uploaded knowledge documents.

The scanner is deliberately generic: rules describe attack language, never a project,
filename, or customer.  A finding is evidence for an Admin, while the configured threshold
decides whether that evidence is strong enough to quarantine the whole document.
"""

import re
from dataclasses import dataclass, replace
from typing import Literal

from backend.core.config import settings
from backend.services.parser_service import ParsedSection

SecuritySeverity = Literal["warning", "high_risk"]
SecurityBlockThreshold = Literal["warning", "high_risk", "disabled"]


@dataclass(frozen=True)
class SecurityRule:
    rule_id: str
    severity: SecuritySeverity
    description: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class SecurityFinding:
    rule_id: str
    severity: SecuritySeverity
    description: str
    page: int | None
    excerpt: str

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "description": self.description,
            "page": self.page,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class SecurityScanResult:
    sections: tuple[ParsedSection, ...]
    findings: tuple[SecurityFinding, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(section.text for section in self.sections)

    def should_block(self, threshold: SecurityBlockThreshold | None = None) -> bool:
        configured = threshold or settings.document_security_block_threshold
        if configured == "disabled":
            return False
        minimum = {"warning": 1, "high_risk": 2}[configured]
        return any({"warning": 1, "high_risk": 2}[finding.severity] >= minimum for finding in self.findings)


_FLAGS = re.IGNORECASE | re.DOTALL

_RULES: tuple[SecurityRule, ...] = (
    SecurityRule(
        rule_id="instruction_override_with_action",
        severity="high_risk",
        description="Yêu cầu bỏ qua chỉ dẫn hiện tại và thực hiện một hành động khác.",
        pattern=re.compile(
            r"\b(?:ignore|disregard|forget|bypass)\s+"
            r"(?:(?:all|any|the|your|previous|prior|above|earlier|system)\s+){0,4}"
            r"(?:instructions?|rules?|prompt)\b.{0,160}?"
            r"(?:\band\b|\bthen\b|\bto\b|[,;:])\s*"
            r"(?:reveal|show|print|return|output|disclose|expose|leak|send|provide|"
            r"follow|execute|obey|act|pretend|respond|answer)\b",
            _FLAGS,
        ),
    ),
    SecurityRule(
        rule_id="vietnamese_instruction_override_with_action",
        severity="high_risk",
        description="Yêu cầu bỏ qua chỉ dẫn bằng tiếng Việt và thực hiện hành động khác.",
        pattern=re.compile(
            r"\b(?:bỏ\s+qua|phớt\s+lờ)\s+"
            r"(?:(?:mọi|toàn\s+bộ|các|những|hướng\s+dẫn|chỉ\s+dẫn|quy\s+tắc)\s+){1,5}"
            r".{0,160}?(?:\bvà\b|\brồi\b|\bđể\b|[,;:])\s*"
            r"(?:tiết\s+lộ|hiển\s+thị|in|trả\s+lời|thực\s+hiện|làm\s+theo|gửi|cung\s+cấp)\b",
            _FLAGS,
        ),
    ),
    SecurityRule(
        rule_id="system_role_with_action",
        severity="high_risk",
        description="Khối giả mạo vai trò hệ thống chứa chỉ thị điều khiển mô hình.",
        pattern=re.compile(
            r"<\s*system\s*>.{0,320}?"
            r"(?:ignore|disregard|reveal|execute|follow\s+these|do\s+not\s+follow|bỏ\s+qua|tiết\s+lộ)\b",
            _FLAGS,
        ),
    ),
    SecurityRule(
        rule_id="instruction_override_reference",
        severity="warning",
        description="Có nhắc tới việc bỏ qua chỉ dẫn hoặc quy tắc.",
        pattern=re.compile(
            r"\b(?:ignore|disregard|forget|bypass)\b.{0,100}?\b(?:instructions?|rules?|prompt)\b",
            _FLAGS,
        ),
    ),
    SecurityRule(
        rule_id="system_prompt_reference",
        severity="warning",
        description="Có nhắc tới system prompt; đây có thể chỉ là nội dung mô tả thông thường.",
        pattern=re.compile(r"\bsystem\s+prompt\b", _FLAGS),
    ),
    SecurityRule(
        rule_id="chatgpt_role_reference",
        severity="warning",
        description="Có câu mô tả vai trò ChatGPT; chưa đủ để kết luận là chỉ thị tấn công.",
        pattern=re.compile(r"\byou\s+are\s+chatgpt\b", _FLAGS),
    ),
    SecurityRule(
        rule_id="jailbreak_reference",
        severity="warning",
        description="Có nhắc tới jailbreak; từ khóa đơn lẻ không làm tài liệu bị chặn.",
        pattern=re.compile(r"\bjailbreak\b", _FLAGS),
    ),
    SecurityRule(
        rule_id="system_tag_reference",
        severity="warning",
        description="Có thẻ system; chỉ bị chặn nếu thẻ này kèm chỉ thị điều khiển.",
        pattern=re.compile(r"<\s*system\s*>", _FLAGS),
    ),
)


def scan_document_sections(sections: list[ParsedSection]) -> SecurityScanResult:
    """Sanitise parsed sections and return bounded, page-aware security evidence."""
    cleaned_sections = tuple(
        replace(section, text=cleaned) for section in sections if (cleaned := section.text.replace("\x00", "").strip())
    )
    if not cleaned_sections:
        return SecurityScanResult(sections=(), findings=())

    findings: list[SecurityFinding] = []
    for section in cleaned_sections:
        for rule in _RULES:
            for match in rule.pattern.finditer(section.text):
                findings.append(
                    SecurityFinding(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        description=rule.description,
                        page=section.page,
                        excerpt=_excerpt(section.text, match.start(), match.end()),
                    )
                )
                if len(findings) >= settings.document_security_max_findings:
                    return SecurityScanResult(sections=cleaned_sections, findings=tuple(findings))

    return SecurityScanResult(sections=cleaned_sections, findings=tuple(findings))


def _excerpt(text: str, start: int, end: int) -> str:
    radius = settings.document_security_excerpt_context_chars
    excerpt = " ".join(text[max(0, start - radius) : min(len(text), end + radius)].split())
    prefix = "…" if start > radius else ""
    suffix = "…" if end + radius < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"
