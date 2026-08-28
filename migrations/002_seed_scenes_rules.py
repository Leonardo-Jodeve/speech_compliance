"""
数据库迁移 002：写入示例场景与规则种子数据（手册 #20）。

示例场景：
- 90131206 加价加约/续约
- 99932000200014 其他
- 999320002000059 4升5,5改5（样例数据中场景 id 实际为 99932000200059）

规则示例（手册 #20）：
- DISCLOSE_DISCOUNT_PERIOD 优惠期限告知（REQUIRED）
- NO_PERMANENT_DISCOUNT 禁止承诺永久优惠（FORBIDDEN）
- DISCLOSE_CONTRACT_PERIOD 合约期限告知（CONDITIONAL_REQUIRED）
- CONFIRM_CUSTOMER_INTENT 确认客户办理意愿（REQUIRED）

用法：
    python migrations/002_seed_scenes_rules.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config.settings import load_config  # noqa: E402

SEED_SCENES = [
    {"source_scene_id": "90131206", "scene_name": "加价加约/续约",
     "description": "加价加约/续约营销场景"},
    {"source_scene_id": "99932000200014", "scene_name": "其他",
     "description": "其他营销场景"},
    {"source_scene_id": "99932000200059", "scene_name": "4升5,5改5",
     "description": "4升5,5改5 场景"},
]

# 规则：rule_code 稳定唯一（手册 #16）
SEED_RULES = [
    {
        "rule_code": "DISCOUNT_DISCOUNT_PERIOD",
        "rule_name": "优惠信息告知",
        "rule_type": "REQUIRED",
        "description": "介绍限时优惠时应明确告知客户优惠期限",
        "standard_expression": "本次优惠期限为12个月，到期后按届时标准资费执行",
        "judge_instruction": "不要求逐字一致。明确表达优惠持续一年、12个月等语义等价内容即可视为满足。",
        "severity": "HIGH",
        "weight": 20,
    },
    {
        "rule_code": "NO_PERMANENT_DISCOUNT",
        "rule_name": "禁止承诺永久优惠",
        "rule_type": "FORBIDDEN",
        "description": "不得向客户承诺优惠永久有效或价格永久不变",
        "standard_expression": None,
        "judge_instruction": "若员工明确表示永久优惠、永远不会涨价、以后一直是该价格等，应判断为 FAIL。",
        "severity": "CRITICAL",
        "weight": 30,
    },
    {
        "rule_code": "DISCLOSE_CONTRACT_PERIOD",
        "rule_name": "合约期限告知",
        "rule_type": "CONDITIONAL_REQUIRED",
        "description": "若介绍合约/套餐优惠，则必须同时说明合约期限",
        "standard_expression": "该合约期限为24个月",
        "judge_instruction": "当员工介绍合约或优惠时，若未说明合约期限则 FAIL；若未介绍合约则 NOT_APPLICABLE。",
        "severity": "HIGH",
        "weight": 20,
    },
    {
        "rule_code": "CONFIRM_CUSTOMER_INTENT",
        "rule_name": "确认客户办理意愿",
        "rule_type": "REQUIRED",
        "description": "员工应确认客户明确同意办理该业务",
        "standard_expression": "确认您需要办理该业务，对吗？",
        "judge_instruction": "员工应明确得到客户同意办理的确认。若客户未同意或含糊，判断为 FAIL。",
        "severity": "HIGH",
        "weight": 15,
    },
]

# 场景 -> 规则关联
SEED_SCENE_RULES = {
    "90131206": ["DISCOUNT_DISCOUNT_PERIOD", "NO_PERMANENT_DISCOUNT", "DISCLOSE_CONTRACT_PERIOD", "CONFIRM_CUSTOMER_INTENT"],
    "99932000200014": ["NO_PERMANENT_DISCOUNT"],
    "99932000200059": ["NO_PERMANENT_DISCOUNT"],
}


def main() -> None:
    cfg = load_config()
    dsn = (
        f"postgresql://{cfg.db_username}:{cfg.db_password}"
        f"@{cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
    )
    schema = cfg.db_schema or "public"
    engine = create_engine(dsn)

    with engine.begin() as conn:
        scene_ids: dict[str, int] = {}
        for sc in SEED_SCENES:
            row = conn.execute(
                text(
                    f"""
                    INSERT INTO {schema}.qc_scene (source_scene_id, scene_name, description, enabled)
                    VALUES (:sid, :name, :desc, TRUE)
                    ON CONFLICT (source_scene_id) DO UPDATE SET
                        scene_name = EXCLUDED.scene_name,
                        description = EXCLUDED.description,
                        updated_at = now()
                    RETURNING id
                    """
                ),
                {"sid": sc["source_scene_id"], "name": sc["scene_name"], "desc": sc["description"]},
            ).one()
            scene_ids[sc["source_scene_id"]] = row.id

        rule_ids: dict[str, int] = {}
        for rule in SEED_RULES:
            row = conn.execute(
                text(
                    f"""
                    INSERT INTO {schema}.qc_rule
                        (rule_code, rule_name, rule_type, description, standard_expression,
                         judge_instruction, severity, weight, enabled)
                    VALUES (:code, :name, :rtype, :desc, :std, :judge, :sev, :weight, TRUE)
                    ON CONFLICT (rule_code) DO UPDATE SET
                        rule_name = EXCLUDED.rule_name,
                        rule_type = EXCLUDED.rule_type,
                        description = EXCLUDED.description,
                        standard_expression = EXCLUDED.standard_expression,
                        judge_instruction = EXCLUDED.judge_instruction,
                        severity = EXCLUDED.severity,
                        weight = EXCLUDED.weight,
                        updated_at = now()
                    RETURNING id
                    """
                ),
                {
                    "code": rule["rule_code"],
                    "name": rule["rule_name"],
                    "rtype": rule["rule_type"],
                    "desc": rule["description"],
                    "std": rule["standard_expression"],
                    "judge": rule["judge_instruction"],
                    "sev": rule["severity"],
                    "weight": rule["weight"],
                },
            ).one()
            rule_ids[rule["rule_code"]] = row.id

        for scene_key, rules in SEED_SCENE_RULES.items():
            sid = scene_ids[scene_key]
            for code in rules:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {schema}.qc_scene_rule (scene_id, rule_id, enabled)
                        VALUES (:sid, :rid, TRUE)
                        ON CONFLICT (scene_id, rule_id) DO UPDATE SET enabled = TRUE
                        """
                    ),
                    {"sid": sid, "rid": rule_ids[code]},
                )

    engine.dispose()
    print(f"迁移 002 完成：schema={schema}，场景 {len(SEED_SCENES)} 个，规则 {len(SEED_RULES)} 条")


if __name__ == "__main__":
    main()