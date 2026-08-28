"""
规则系统 Repository（手册 #14-#20）。

三张表：qc_scene / qc_rule / qc_scene_rule（场景与规则多对多）。
核心方法 get_rules_for_call(scene_id, call_time) 加载指定通话时刻有效规则（手册 #19）：
  场景启用 + 规则启用 + effective_from <= call_time < effective_to。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config.logging import get_logger
from ..domain.rule import ComplianceRule, RuleType, Severity
from ..domain.scenario import MarketingScenario

logger = get_logger(__name__)


class ScenarioRepository:
    """qc_scene 表操作。"""

    def __init__(self, engine: Engine, schema: str = "public") -> None:
        self._engine = engine
        self._schema = schema

    def _t(self, table: str) -> str:
        """返回带 schema 前缀的表名；schema 为空时直接用表名（测试用）。"""
        return f"{self._schema}.{table}" if self._schema else table

    def upsert_scene(self, scene: MarketingScenario) -> int:
        sql = text(
            f"""
            INSERT INTO {self._t('qc_scene')}
                (source_scene_id, scene_name, description, enabled)
            VALUES (:source_scene_id, :scene_name, :description, :enabled)
            ON CONFLICT (source_scene_id) DO UPDATE SET
                scene_name = EXCLUDED.scene_name,
                description = EXCLUDED.description,
                enabled = EXCLUDED.enabled,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = conn.execute(sql, {
                "source_scene_id": scene.source_scene_id,
                "scene_name": scene.scene_name,
                "description": scene.description,
                "enabled": scene.enabled,
            }).one()
        return row["id"]

    def list_scenes(self) -> list[MarketingScenario]:
        sql = text(
            f"SELECT id, source_scene_id, scene_name, description, enabled "
            f"FROM {self._t('qc_scene')} ORDER BY source_scene_id"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()
        return [
            MarketingScenario(
                id=r["id"],
                source_scene_id=r["source_scene_id"],
                scene_name=r["scene_name"],
                description=r["description"],
                enabled=bool(r["enabled"]),
            )
            for r in rows
        ]

    def get_scene(self, source_scene_id: str) -> MarketingScenario | None:
        sql = text(
            f"SELECT id, source_scene_id, scene_name, description, enabled "
            f"FROM {self._t('qc_scene')} WHERE source_scene_id = :sid"
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"sid": str(source_scene_id)}).mappings().first()
        if not row:
            return None
        return MarketingScenario(
            id=row["id"],
            source_scene_id=row["source_scene_id"],
            scene_name=row["scene_name"],
            description=row["description"],
            enabled=bool(row["enabled"]),
        )


class RuleRepository:
    """规则 Repository：场景-规则多对多加载。"""

    def __init__(self, engine: Engine, schema: str = "public") -> None:
        self._engine = engine
        self._schema = schema

    def _t(self, table: str) -> str:
        """返回带 schema 前缀的表名；schema 为空时直接用表名（测试用）。"""
        return f"{self._schema}.{table}" if self._schema else table

    def get_rules_for_call(
        self,
        scene_id: str,
        call_time: _dt.datetime | None = None,
    ) -> list[ComplianceRule]:
        """加载某场景在 call_time 时刻有效的规则（手册 #19）。

        - 场景必须 enabled；
        - 规则必须 enabled；
        - rule.effective_from <= call_time；
        - rule.effective_to IS NULL 或 > call_time；
        - 通过 qc_scene_rule 关联。
        """
        sql = text(
            f"""
            SELECT r.id, r.rule_code, r.rule_name, r.rule_type, r.description,
                   r.standard_expression, r.judge_instruction,
                   r.severity, COALESCE(sr.weight_override, r.weight) AS weight,
                   r.effective_from, r.effective_to, r.enabled,
                   r.revision_id, r.content_hash
            FROM {self._t('qc_scene')} s
            JOIN {self._t('qc_scene_rule')} sr ON sr.scene_id = s.id
            JOIN {self._t('qc_rule')} r       ON r.id = sr.rule_id
            WHERE s.source_scene_id = :scene_id
              AND s.enabled = TRUE
              AND sr.enabled = TRUE
              AND r.enabled = TRUE
              AND (r.effective_from IS NULL OR r.effective_from <= :call_time)
              AND (r.effective_to IS NULL OR r.effective_to > :call_time)
            ORDER BY r.rule_code
            """
        )
        params: dict = {
            "scene_id": str(scene_id),
            "call_time": call_time or _dt.datetime.now(),
        }
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()

        rules = [self._to_rule(r) for r in rows]
        logger.info(
            "get_rules_for_call scene=%s rules=%s", scene_id, len(rules),
            extra={"task_id": None, "source_call_key": None, "scene_id": str(scene_id), "stage": "RULES"},
        )
        return rules

    def list_rules(self) -> list[ComplianceRule]:
        sql = text(
            f"""
            SELECT id, rule_code, rule_name, rule_type, description,
                   standard_expression, judge_instruction, severity, weight,
                   effective_from, effective_to, enabled, revision_id, content_hash
            FROM {self._t('qc_rule')} ORDER BY rule_code
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql).mappings().all()
        return [self._to_rule(r) for r in rows]

    @staticmethod
    def _to_rule(r) -> ComplianceRule:
        return ComplianceRule(
            id=r["id"],
            rule_code=r["rule_code"],
            rule_name=r["rule_name"],
            rule_type=RuleType(r["rule_type"]),
            description=r["description"],
            standard_expression=r["standard_expression"],
            judge_instruction=r["judge_instruction"],
            severity=Severity(r["severity"]),
            weight=float(r["weight"]),
            effective_from=r["effective_from"],
            effective_to=r["effective_to"],
            enabled=bool(r["enabled"]),
            revision_id=r["revision_id"],
            content_hash=r["content_hash"],
        )


def content_hash_of(rule: ComplianceRule) -> str:
    """规则内容哈希，用于技术审计（手册 #19）。"""
    raw = "|".join([
        rule.rule_code,
        rule.rule_name,
        rule.rule_type.value,
        rule.description or "",
        rule.standard_expression or "",
        rule.judge_instruction or "",
        rule.severity.value,
        str(rule.weight),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()