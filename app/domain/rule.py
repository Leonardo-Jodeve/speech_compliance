"""话术合规规则领域模型（手册 #16/#17/#19/#20）。"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum


class RuleType(str, Enum):
    REQUIRED = "REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    CONDITIONAL_REQUIRED = "CONDITIONAL_REQUIRED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ComplianceRule:
    """对应 qc_rule 表（手册 #16）。

    rule_code 必须稳定且唯一，例如 DISCLOSE_CONTRACT_PERIOD。
    effective_from/effective_to 用于历史规则（手册 #19）：
    8 月新增的规则不会拿去判断 7 月录音。
    """

    rule_code: str
    rule_name: str
    rule_type: RuleType = RuleType.REQUIRED
    description: str | None = None
    standard_expression: str | None = None
    judge_instruction: str | None = None
    severity: Severity = Severity.MEDIUM
    weight: float = 10.0
    effective_from: _dt.datetime | None = None
    effective_to: _dt.datetime | None = None
    enabled: bool = True
    id: int | None = None
    revision_id: str | None = None
    content_hash: str | None = None

    def to_prompt_dict(self) -> dict:
        """仅把供 LLM 判断所需的字段序列化进 Prompt（手册 #27）。"""
        return {
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type.value,
            "description": self.description or "",
            "standard_expression": self.standard_expression or "",
            "judge_instruction": self.judge_instruction or "",
        }