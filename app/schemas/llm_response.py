"""LLM 返回的 JSON Schema（手册 #28/#29），使用 Pydantic 强校验。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuleEvaluationModel(BaseModel):
    """单条规则判断。status 限定四值，confidence 范围 [0,1]。"""

    rule_code: str
    status: Literal["PASS", "FAIL", "NOT_APPLICABLE", "REVIEW"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    evidence: list[str]


class ComplianceResponseModel(BaseModel):
    """LLM 返回整体结构（手册 #28）。"""

    rule_results: list[RuleEvaluationModel]