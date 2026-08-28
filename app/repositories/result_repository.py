"""
质检结果 Repository（手册 #38/#39/#40）。

表：
- qc_transcript：ASR 转写
- qc_result：总体结果
- qc_rule_result：逐规则结果
"""
from __future__ import annotations

import datetime as _dt
import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config.logging import get_logger
from ..domain.compliance import ComplianceResult, RuleEvaluation

logger = get_logger(__name__)


class TranscriptRepository:
    """qc_transcript 表操作（手册 #38）。"""

    def __init__(self, engine: Engine, schema: str = "public") -> None:
        self._engine = engine
        self._schema = schema

    def save(
        self,
        task_id: int,
        source_call_key: str,
        asr_file_id: str | None,
        transcript_text: str,
        raw_answer: str,
    ) -> int:
        sql = text(
            f"""
            INSERT INTO {self._schema}.qc_transcript
                (task_id, source_call_key, asr_file_id, transcript_text, raw_answer)
            VALUES (:task_id, :source_call_key, :asr_file_id, :transcript_text, :raw_answer)
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = conn.execute(sql, {
                "task_id": task_id,
                "source_call_key": source_call_key,
                "asr_file_id": asr_file_id,
                "transcript_text": transcript_text,
                "raw_answer": raw_answer,
            }).one()
        return row.id


class ResultRepository:
    """qc_result + qc_rule_result 保存（手册 #39/#40）。"""

    def __init__(self, engine: Engine, schema: str = "public") -> None:
        self._engine = engine
        self._schema = schema

    def save_result(self, result: ComplianceResult, task_id: int) -> int:
        sql = text(
            f"""
            INSERT INTO {self._schema}.qc_result
                (task_id, source_call_key, scene_id, scene_name,
                 seat_id, seat_name, score, overall_status,
                 total_rules, passed_rules, failed_rules, review_rules, not_applicable_rules,
                 summary)
            VALUES
                (:task_id, :source_call_key, :scene_id, :scene_name,
                 :seat_id, :seat_name, :score, :overall_status,
                 :total_rules, :passed_rules, :failed_rules, :review_rules, :not_applicable_rules,
                 :summary)
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            row = conn.execute(sql, {
                "task_id": task_id,
                "source_call_key": result.source_call_key,
                "scene_id": result.scene_id,
                "scene_name": result.scene_name,
                "seat_id": result.seat_id,
                "seat_name": result.seat_name,
                "score": result.score,
                "overall_status": result.overall_status.value,
                "total_rules": result.total_rules,
                "passed_rules": result.passed_rules,
                "failed_rules": result.failed_rules,
                "review_rules": result.review_rules,
                "not_applicable_rules": result.not_applicable_rules,
                "summary": result.summary,
            }).one()
        return row.id

    def save_rule_results(self, result_id: int, evaluations: list[RuleEvaluation]) -> None:
        if not evaluations:
            return
        rows = [
            (
                result_id,
                e.rule_code,
                e.rule_name,
                e.rule_type,
                e.severity,
                e.weight,
                e.status.value,
                e.confidence,
                e.reason,
                json.dumps(e.evidence, ensure_ascii=False),
                e.evidence_verified,
            )
            for e in evaluations
        ]
        sql = text(
            f"""
            INSERT INTO {self._schema}.qc_rule_result
                (result_id, rule_code, rule_name, rule_type, severity, weight,
                 status, confidence, reason, evidence_json, evidence_verified)
            VALUES
                (:result_id, :rule_code, :rule_name, :rule_type, :severity, :weight,
                 :status, :confidence, :reason, :evidence_json, :evidence_verified)
            """
        )
        with self._engine.begin() as conn:
            for r in rows:
                conn.execute(sql, {
                    "result_id": r[0],
                    "rule_code": r[1],
                    "rule_name": r[2],
                    "rule_type": r[3],
                    "severity": r[4],
                    "weight": r[5],
                    "status": r[6],
                    "confidence": r[7],
                    "reason": r[8],
                    "evidence_json": r[9],
                    "evidence_verified": r[10],
                })