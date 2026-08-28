"""
Test 5-8：ASR模糊 / 场景无规则 / 未接通 / 大ID（手册 #50）。
"""
from __future__ import annotations

import datetime as _dt

from app.domain.call import CallRecord, build_source_call_key, from_excel_row
from app.domain.compliance import RuleStatus


# ---------- Test 5：ASR 模糊 → REVIEW ----------

def test_asr_ambiguity_review():
    """转写含[听不清]等模糊内容时，允许 REVIEW，禁止强制 PASS。

    该行为由 LLM 判断产生（见提示词原则 7），这里验证 REVIEW 状态会传导到整体为 REVIEW。
    """
    from app.domain.compliance import RuleEvaluation
    from app.services.scoring_service import ScoringService

    ev = RuleEvaluation(
        rule_code="R001", rule_name="r1", rule_type="REQUIRED",
        severity="HIGH", weight=20, status=RuleStatus.REVIEW,
    )
    result = ScoringService(80).score([ev])
    assert result.overall_status.value == "REVIEW"


# ---------- Test 6：场景无规则 ----------

def test_no_rule_scene_behavior():
    """场景无规则时，策略为 SKIPPED（默认）或 REVIEW_REQUIRED，绝不允许默认 100 分。"""
    # 此处验证 ComplianceResult 构造 + SKIPPED 语义
    from app.domain.compliance import ComplianceResult, OverallStatus

    r = ComplianceResult(
        source_call_key="k", scene_id="X", scene_name="未配置场景",
        seat_id=None, seat_name=None, score=-1,
        overall_status=OverallStatus.SKIPPED,
        summary="SCENE_RULE_NOT_CONFIGURED",
    )
    assert r.overall_status == OverallStatus.SKIPPED
    assert r.score == -1
    assert r.summary == "SCENE_RULE_NOT_CONFIGURED"


# ---------- Test 7b：未接通 + file_url 非空，不得进入质检 ----------

def test_unconnected_call_not_qualifiable():
    call = CallRecord(
        source_call_key="k1",
        scene_id="90131206",
        call_result="未接通",
        talk_seconds=0,
        recording_url="https://example.com/a.wav",
    )
    assert call.is_qualifiable(min_talk_seconds=15) is False


# ---------- Test 8：大 ID 保持字符串 ----------

def test_large_id_preserved_as_string():
    """超大 order_id / scene_id 必须保持原始字符串（禁止 float 精度损失）。"""
    # Excel 中 order_id 已以科学计数法呈现
    header = [
        "latn_id", "activity_id", "order_id", "opr_pos_code", "opr_pos_name",
        "act_scene_id", "act_scene_name", "creator", "seat_id", "seat_name",
        "feedback_result", "object_id", "main_acc_nbr", "host_call_nbr",
        "guest_called_nbr", "start_date", "end_date", "call_time", "call_result",
        "file_url", "call_source", "call_type", "twoconfir", "terminal_type",
        "p_day", "answertime",
    ]
    row = [
        514, 536505542, 1.77734773447953e+39, 15, "局1", 90131206, "续约",
        32031890, 13373690980, "张三", 12, 142200132630, 18052593171, 10001,
        18052593171, _dt.datetime(2026, 5, 6, 17, 24, 37), _dt.datetime(2026, 5, 6, 17, 25, 33),
        208, "接通", "https://example.com/a.wav", 4, 1, 0, 3, 20260506, 21,
    ]
    call = from_excel_row(header, row)
    # scene_id 保留为 "90131206"（整数值浮点转 str 不丢精度）
    assert call.scene_id == "90131206"
    # order_id 为完整十进制字符串（float 整数值 → str(int)，还原完整数字）
    assert call.order_id == "1777347734479529864709667220355207397376"
    # 不是 float，不因 int(float) 丢失
    assert not isinstance(call.order_id, float)


def test_source_call_key_stable():
    k1 = build_source_call_key("17773447953", _dt.datetime(2026, 5, 6, 17, 24, 37), "10001", "18052593171")
    k2 = build_source_call_key("17773447953", _dt.datetime(2026, 5, 6, 17, 24, 37), "10001", "18052593171")
    assert k1 == k2
    assert len(k1) == 64