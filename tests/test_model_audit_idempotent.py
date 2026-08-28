"""
Test 9-12：模型虚构规则 / 模型缺规则 / Evidence幻觉 / 幂等（手册 #50）。
"""
from __future__ import annotations

import datetime as _dt

from app.domain.call import CallRecord
from app.domain.rule import ComplianceRule, RuleType, Severity
from app.schemas.llm_response import ComplianceResponseModel, RuleEvaluationModel


def _rules():
    return [
        ComplianceRule(rule_code="R001", rule_name="规则1", rule_type=RuleType.REQUIRED,
                       severity=Severity.HIGH, weight=20),
        ComplianceRule(rule_code="R002", rule_name="规则2", rule_type=RuleType.REQUIRED,
                       severity=Severity.HIGH, weight=20),
        ComplianceRule(rule_code="R003", rule_name="规则3", rule_type=RuleType.REQUIRED,
                       severity=Severity.HIGH, weight=20),
    ]


def _resp(items: list[dict]) -> ComplianceResponseModel:
    return ComplianceResponseModel.model_validate({"rule_results": items})


# ---------- Test 9：模型虚构规则 ----------

def test_model_fabricates_rule_is_rejected():
    from app.adapters.tokenhub_adapter import LlmAdapter

    rules = _rules()[:2]  # R001 R002
    resp = _audit_wrapper(LlmAdapter, rules, [
        {"rule_code": "R001", "status": "PASS", "confidence": 0.9, "reason": "ok", "evidence": []},
        {"rule_code": "R002", "status": "PASS", "confidence": 0.9, "reason": "ok", "evidence": []},
        {"rule_code": "R003", "status": "FAIL", "confidence": 0.9, "reason": "fabricated", "evidence": []},
    ])
    codes = {r.rule_code for r in resp.rule_results}
    assert codes == {"R001", "R002"}
    assert "R003" not in codes


# ---------- Test 10：模型缺规则 ----------

def test_model_missing_rule_becomes_review():
    from app.adapters.tokenhub_adapter import LlmAdapter

    rules = _rules()  # R001 R002 R003
    resp = _audit_wrapper(LlmAdapter, rules, [
        {"rule_code": "R001", "status": "PASS", "confidence": 0.9, "reason": "ok", "evidence": []},
        {"rule_code": "R003", "status": "PASS", "confidence": 0.9, "reason": "ok", "evidence": []},
    ])
    by_code = {r.rule_code: r.status for r in resp.rule_results}
    assert set(by_code) == {"R001", "R002", "R003"}
    assert by_code["R002"] == "REVIEW"  # 缺失规则 → REVIEW，不能消失


def _audit_wrapper(adapter_cls, rules, items):
    """通过 LlmAdapter 静态方法执行审计。"""
    model_resp = _audit(items)
    adapter_cls._audit_rules(model_resp, rules)
    return model_resp


def _audit(items):
    return _resp(items)


def _resp(items):
    return ComplianceResponseModel.model_validate({"rule_results": items})


# ---------- Test 11：Evidence 幻觉 ----------

def test_evidence_hallucination_detected():
    from app.services.evidence_service import verify_evidence_list

    transcript = "您好，这个价格可以享受一年，到期后恢复原价。"
    # 真实存在
    verified, missing = verify_evidence_list(["这个价格可以享受一年"], transcript)
    assert verified is True
    # 幻觉：不存在于转写
    verified, missing = verify_evidence_list(["这个套餐永远不会涨价"], transcript)
    assert verified is False
    assert missing == ["这个套餐永远不会涨价"]


def test_evidence_normalization_allows_punct_spaces():
    from app.services.evidence_service import evidence_exists_in_transcript

    assert evidence_exists_in_transcript("这个价格，可以享受一年", "您好！ 这个价格可以享受一年。") is True


# ---------- Test 12：幂等 ----------

def test_idempotent_task_creation(engine):
    """同一 source_call_key 连续 create 两次，不得产生两份任务。"""
    from sqlalchemy import text as sqla_text

    from app.repositories.task_repository import TaskRepository

    repo = TaskRepository(engine, schema="")
    t1 = repo.create_task(
        source_call_key="abc123", order_id="1", scene_id="s1", scene_name="场景",
        seat_id=None, seat_name=None, recording_url="http://x/1.wav",
    )
    t2 = repo.create_task(
        source_call_key="abc123", order_id="1", scene_id="s1", scene_name="场景",
        seat_id=None, seat_name=None, recording_url="http://x/1.wav",
    )
    with engine.connect() as conn:
        cnt = conn.execute(sqla_text("SELECT COUNT(*) FROM qc_task")).scalar()
    assert cnt == 1
    assert t1 == t2  # 同一任务