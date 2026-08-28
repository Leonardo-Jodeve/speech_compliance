"""
Test 1-4：场景隔离 / 语义等价 / 禁止话术 / 条件规则（手册 #50）。

这些测试聚焦：
- 规则按场景加载（场景隔离）；
- 语义等价判断由 LLM 负责，但程序层确保规则通过标准表达 + 判断指令传递；
- 评分服务对 FORBIDDEN 违规给出 FAIL；
- 条件规则未触发给出 NOT_APPLICABLE 语义。
"""
from __future__ import annotations

from app.domain.compliance import RuleEvaluation, RuleStatus
from app.domain.rule import ComplianceRule, RuleType, Severity
from app.services.scoring_service import ScoringService


def _rule(code: str, rtype: RuleType = RuleType.REQUIRED, severity=Severity.HIGH, weight=20) -> ComplianceRule:
    return ComplianceRule(
        rule_code=code,
        rule_name=code,
        rule_type=rtype,
        severity=severity,
        weight=weight,
    )


# ---------- Test 1：场景隔离 ----------

def test_scene_isolation_rule_loading(engine):
    """场景A加载RULE_A1/A2，场景B加载RULE_B1，互不泄漏。

    验证 get_rules_for_call 的场景过滤逻辑。使用 sqlite 引擎手工插入数据。
    """
    from sqlalchemy import text as sqla_text

    from app.repositories.rule_repository import RuleRepository

    with engine.begin() as conn:
        conn.execute(sqla_text("INSERT INTO qc_scene (source_scene_id, scene_name) VALUES ('A', '场景A')"))
        conn.execute(sqla_text("INSERT INTO qc_scene (source_scene_id, scene_name) VALUES ('B', '场景B')"))
        conn.execute(sqla_text(
            "INSERT INTO qc_rule (rule_code, rule_name, rule_type) VALUES "
            "('RULE_A1','规则A1','REQUIRED'), ('RULE_A2','规则A2','REQUIRED'), ('RULE_B1','规则B1','REQUIRED')"
        ))
        rows = conn.execute(sqla_text("SELECT id, source_scene_id FROM qc_scene")).all()
        scene_ids = {r[1]: r[0] for r in rows}
        rule_rows = conn.execute(sqla_text("SELECT id, rule_code FROM qc_rule")).all()
        rule_ids = {r[1]: r[0] for r in rule_rows}
        for scene_key, codes in (("A", ["RULE_A1", "RULE_A2"]), ("B", ["RULE_B1"])):
            for code in codes:
                conn.execute(sqla_text(
                    "INSERT INTO qc_scene_rule (scene_id, rule_id) VALUES (:sid, :rid)"
                ), {"sid": scene_ids[scene_key], "rid": rule_ids[code]})

    repo = RuleRepository(engine, schema="")
    rules_a = {r.rule_code for r in repo.get_rules_for_call("A")}
    rules_b = {r.rule_code for r in repo.get_rules_for_call("B")}

    assert rules_a == {"RULE_A1", "RULE_A2"}
    assert rules_b == {"RULE_B1"}
    # 场景A绝不能加载RULE_B1
    assert "RULE_B1" not in rules_a


# ---------- Test 2：语义等价（标准表达 vs 等价表达） ----------

def test_semantic_equivalence_prompt_contains_standard_and_instruction():
    """规则对象必须携带 standard_expression 与 judge_instruction，供 LLM 判断语义等价。"""
    rule = _rule("DISCOUNT_DISCOUNT_PERIOD")
    rule.standard_expression = "本次优惠期限为12个月"
    rule.judge_instruction = "不要求逐字一致。明确表达优惠持续一年、12个月等语义等价内容即可视为满足。"
    d = rule.to_prompt_dict()
    assert d["standard_expression"] == "本次优惠期限为12个月"
    assert "语义等价" in d["judge_instruction"]


# ---------- Test 3：禁止话术 → 评分 FAIL ----------

def test_forbidden_phrase_leads_to_fail():
    """FORBIDDEN 规则被判 FAIL 后，整体应为 FAIL（含 CRITICAL 强制）。"""
    ev = RuleEvaluation(
        rule_code="NO_PERMANENT_DISCOUNT",
        rule_name="禁止承诺永久优惠",
        rule_type="FORBIDDEN",
        severity="CRITICAL",
        weight=30,
        status=RuleStatus.FAIL,
    )
    result = ScoringService(80).score([ev])
    assert result.overall_status.value == "FAIL"
    assert result.failed_rules == 1


# ---------- Test 4：条件规则未触发 ----------

def test_conditional_not_triggered_is_not_applicable():
    """条件规则未触发 → NOT_APPLICABLE 不计入分母，不导致 FAIL。"""
    ev = RuleEvaluation(
        rule_code="DISCLOSE_CONTRACT_PERIOD",
        rule_name="合约期限告知",
        rule_type="CONDITIONAL_REQUIRED",
        severity="HIGH",
        weight=20,
        status=RuleStatus.NOT_APPLICABLE,
    )
    result = ScoringService(80).score([ev])
    assert result.not_applicable_rules == 1
    assert result.overall_status.value == "PASS"
    assert result.score == 100.0