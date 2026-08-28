"""合规质检结果领域模型（手册 #28/#29/#34）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REVIEW = "REVIEW"


class OverallStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class RuleEvaluation:
    """单条规则的最终判定结果（由 LLM 判断 + 程序校验后形成）。"""

    rule_code: str
    rule_name: str
    rule_type: str
    severity: str
    weight: float
    status: RuleStatus
    confidence: float = 0.0
    reason: str = ""
    evidence: list[str] = field(default_factory=list)
    evidence_verified: bool = True


@dataclass
class ComplianceResult:
    """单通通话的质检总体结果。"""

    source_call_key: str
    scene_id: str
    scene_name: str
    seat_id: str | None
    seat_name: str | None
    score: float
    overall_status: OverallStatus
    rule_results: list[RuleEvaluation] = field(default_factory=list)
    summary: str = ""
    error_code: str | None = None
    error_message: str | None = None
    perf: dict | None = field(default_factory=dict)  # 性能统计（手册 #49）

    @property
    def total_rules(self) -> int:
        return len(self.rule_results)

    @property
    def passed_rules(self) -> int:
        return sum(1 for r in self.rule_results if r.status == RuleStatus.PASS)

    @property
    def failed_rules(self) -> int:
        return sum(1 for r in self.rule_results if r.status == RuleStatus.FAIL)

    @property
    def review_rules(self) -> int:
        return sum(1 for r in self.rule_results if r.status == RuleStatus.REVIEW)

    @property
    def not_applicable_rules(self) -> int:
        return sum(1 for r in self.rule_results if r.status == RuleStatus.NOT_APPLICABLE)


# ---------- LLM 输出 Schema（手册 #29） ----------

@dataclass
class LlmRuleResult:
    """LLM 单条规则判断输出（经过 Pydantic 校验）。"""

    rule_code: str
    status: RuleStatus
    confidence: float
    reason: str
    evidence: list[str]


@dataclass
class ComplianceModelResponse:
    """LLM 整体输出。"""

    rule_results: list[LlmRuleResult] = field(default_factory=list)