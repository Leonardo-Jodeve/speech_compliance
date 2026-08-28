"""
评分服务（手册 #33/#34）。

LLM 只负责逐规则语义判断，最终 score / overall_status / critical_fail 全部由本 Python 服务计算。
规则：
- applicable_weight = pass_weight + fail_weight（NOT_APPLICABLE 不进入分母）；
- score = pass_weight / applicable_weight * 100；
- severity = CRITICAL 且 status = FAIL → overall_status = FAIL；
- 否则 review_count > 0 → REVIEW；
- score >= pass_score → PASS，否则 FAIL。
"""
from __future__ import annotations

from ..domain.compliance import ComplianceResult, OverallStatus, RuleEvaluation, RuleStatus


class ScoringService:
    def __init__(self, pass_score: float = 80.0) -> None:
        self._pass_score = pass_score

    def score(self, evaluations: list[RuleEvaluation]) -> ComplianceResult:
        """根据逐规则结果计算总体结果（不含 LLM）。"""
        pass_weight = sum(e.weight for e in evaluations if e.status == RuleStatus.PASS)
        fail_weight = sum(e.weight for e in evaluations if e.status == RuleStatus.FAIL)
        applicable_weight = pass_weight + fail_weight
        score = round(pass_weight / applicable_weight * 100, 2) if applicable_weight > 0 else 100.0

        critical_fail = any(
            e.severity == "CRITICAL" and e.status == RuleStatus.FAIL
            for e in evaluations
        )
        review_count = sum(1 for e in evaluations if e.status == RuleStatus.REVIEW)

        if critical_fail:
            overall = OverallStatus.FAIL
        elif review_count > 0:
            overall = OverallStatus.REVIEW
        elif score >= self._pass_score:
            overall = OverallStatus.PASS
        else:
            overall = OverallStatus.FAIL

        return ComplianceResult(
            source_call_key="",   # 由调用方补充
            scene_id="",
            scene_name="",
            seat_id=None,
            seat_name=None,
            score=score,
            overall_status=overall,
            rule_results=evaluations,
        )