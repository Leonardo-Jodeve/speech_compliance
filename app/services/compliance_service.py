"""
合规质检编排（手册 #41/#42/#7/#13）。

单通完整链路：
    CallRecord → 资格检查 → 幂等检查 → 创建 qc_task → 下载录音 → ASR
    → 保存 Transcript → 加载规则 → LLM 质检 → Pydantic 校验 → 规则完整性
    → Evidence 校验 → ScoringService → 保存 result → COMPLETED
"""
from __future__ import annotations

import datetime as _dt
import time
import hashlib

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..adapters.asr_adapter import AsrAdapter
from ..adapters.recording_adapter import RecordingAdapter
from ..adapters.tokenhub_adapter import LlmAdapter
from ..config.logging import get_logger
from ..domain.call import CallRecord
from ..domain.compliance import (
    ComplianceResult,
    OverallStatus,
    RuleEvaluation,
    RuleStatus,
)
from ..domain.rule import ComplianceRule
from ..domain.transcript import Transcript
from ..repositories.result_repository import ResultRepository, TranscriptRepository
from ..repositories.rule_repository import RuleRepository
from ..repositories.task_repository import (
    ASR_PROCESSING,
    ASR_COMPLETED,
    COMPLETED,
    DOWNLOADING,
    FAILED,
    LLM_PROCESSING,
    PENDING,
    REVIEW_REQUIRED,
    SKIPPED,
    TaskRepository,
)
from ..services.evidence_service import verify_evidence_list
from ..services.scoring_service import ScoringService

logger = get_logger(__name__)

# 性能字段统计（手册 #49）
PERF_KEYS = ("audio_download_ms", "asr_ms", "llm_ms", "total_ms",
             "llm_input_tokens", "llm_output_tokens", "llm_total_tokens")


class NoRuleConfigured(Exception):
    """场景未配置规则。"""


class ComplianceTaskService:
    """单通任务编排服务。"""

    def __init__(
        self,
        engine: Engine,
        task_repo: TaskRepository,
        transcript_repo: TranscriptRepository,
        result_repo: ResultRepository,
        rule_repo: RuleRepository,
        asr_adapter: AsrAdapter,
        llm_adapter: LlmAdapter,
        recording_adapter: RecordingAdapter,
        scoring_service: ScoringService,
        *,
        min_talk_seconds: int = 15,
        no_rule_behavior: str = "SKIPPED",
        schema: str = "public",
    ) -> None:
        self._engine = engine
        self._tasks = task_repo
        self._transcripts = transcript_repo
        self._results = result_repo
        self._rules = rule_repo
        self._asr = asr_adapter
        self._llm = llm_adapter
        self._recording = recording_adapter
        self._scoring = scoring_service
        self._min_talk_seconds = min_talk_seconds
        self._no_rule_behavior = no_rule_behavior
        self._schema = schema

    # ---------- 主流程 ----------

    def process_call(self, call: CallRecord) -> ComplianceResult:
        """处理单通通话（手册 #41）。返回完整结果，同时写库。"""
        if self._engine.dialect.name != "postgresql":
            return self._process_call(call)
        # 会话锁覆盖完整外部调用；Web 和 CLI 同时提交也不会重复跑同一通。
        lock_id = int.from_bytes(hashlib.sha256(call.source_call_key.encode()).digest()[:8], "big", signed=True)
        with self._engine.connect() as lock_conn:
            acquired = lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id}).scalar()
            lock_conn.commit()
            if not acquired:
                return self._build_skipped_result(call, error_code="TASK_ALREADY_RUNNING")
            try:
                return self._process_call(call)
            finally:
                try:
                    lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                    lock_conn.commit()
                except Exception:
                    lock_conn.invalidate()

    def _process_call(self, call: CallRecord) -> ComplianceResult:
        start_wall = time.perf_counter()
        perf: dict = {k: None for k in PERF_KEYS}

        # 1. 资格检查（手册 #10/#41）
        if not call.is_qualifiable(self._min_talk_seconds):
            return ComplianceResult(
                source_call_key=call.source_call_key,
                scene_id=call.scene_id,
                scene_name=call.scene_name,
                seat_id=call.seat_id,
                seat_name=call.seat_name,
                score=-1,
                overall_status=OverallStatus.SKIPPED,
                summary="通话不具备质检资格（未接通/无录音/时长不足）",
            )

        # 2. 幂等检查（手册 #36/#41，Test 12）
        existing = self._tasks.get_completed_task(call.source_call_key)
        if existing is not None:
            logger.info("幂等跳过：已存在完成任务", extra=self._log_extra(call, "IDEMPOTENT"))
            return self._build_skipped_result(call, error_code="已存在完成任务")

        # 3. 创建 qc_task（ON CONFLICT 幂等）
        task_id = self._tasks.create_task(
            source_call_key=call.source_call_key,
            order_id=call.order_id,
            scene_id=call.scene_id,
            scene_name=call.scene_name,
            seat_id=call.seat_id,
            seat_name=call.seat_name,
            recording_url=call.recording_url,
        )
        if task_id is None:
            raise RuntimeError("创建 qc_task 失败")
        extra = self._log_extra(call, "TASK", task_id)
        logger.info("任务创建 task=%s", task_id, extra=extra)

        try:
            # 4. 下载录音（手册 #23）
            self._tasks.update_stage(task_id, DOWNLOADING, "DOWNLOADING")
            t0 = time.perf_counter()
            local_path = self._recording.download(call.recording_url, task_id, ext="wav")
            perf["audio_download_ms"] = int((time.perf_counter() - t0) * 1000)
            logger.info("录音下载完成", extra=extra)

            # 5. ASR（手册 #21）
            self._tasks.update_stage(task_id, ASR_PROCESSING, "ASR_PROCESSING")
            t0 = time.perf_counter()
            transcript = self._asr.transcribe(str(local_path), task_id=task_id)
            perf["asr_ms"] = int((time.perf_counter() - t0) * 1000)
            self._tasks.update_stage(task_id, ASR_COMPLETED, "ASR_COMPLETED")
            logger.info("ASR完成 text_len=%s", len(transcript.text), extra=extra)

            # 6. 保存 Transcript（手册 #38）
            self._transcripts.save(
                task_id=task_id,
                source_call_key=call.source_call_key,
                asr_file_id=transcript.asr_file_id,
                transcript_text=transcript.text,
                raw_answer=transcript.raw_answer,
            )

            # 7. 加载规则（手册 #19）
            rules = self._rules.get_rules_for_call(call.scene_id, call.start_time)
            if not rules:
                # 场景无规则：禁止默认满分（手册 #42）
                if self._no_rule_behavior == "REVIEW_REQUIRED":
                    self._tasks.update_stage(
                        task_id, REVIEW_REQUIRED, "REVIEW_REQUIRED",
                        error_code="SCENE_RULE_NOT_CONFIGURED",
                        error_message="场景未配置任何有效规则",
                    )
                    return self._build_skipped_result(
                        call, OverallStatus.REVIEW_REQUIRED, "SCENE_RULE_NOT_CONFIGURED"
                    )
                self._tasks.update_stage(
                    task_id, SKIPPED, "SKIPPED",
                    error_code="SCENE_RULE_NOT_CONFIGURED",
                    error_message="场景未配置任何有效规则",
                )
                return self._build_skipped_result(
                    call, OverallStatus.SKIPPED, "SCENE_RULE_NOT_CONFIGURED"
                )

            # 8. LLM 质检（手册 #25/#28/#29）
            self._tasks.update_stage(task_id, LLM_PROCESSING, "LLM_PROCESSING")
            t0 = time.perf_counter()
            model_resp = self._llm.evaluate_rules(transcript, _scenario_of(call), rules)
            perf["llm_ms"] = int((time.perf_counter() - t0) * 1000)

            # 9. 规则完整性：LLM 缺规则已由 adapter 补 REVIEW（#31）

            # 10. Evidence 校验（手册 #32）
            evaluations = []
            for r in rules:
                item = _find_result(model_resp, r.rule_code)
                if item is None:
                    # adapter 已保证完整性，此处兜底
                    ev = RuleEvaluation(
                        rule_code=r.rule_code, rule_name=r.rule_name,
                        rule_type=r.rule_type.value, severity=r.severity.value,
                        weight=r.weight, status=RuleStatus.REVIEW,
                        reason="MODEL_MISSING_RULE_RESULT", evidence=[], evidence_verified=False,
                    )
                else:
                    verified, _missing = verify_evidence_list(item.evidence, transcript.text)
                    # 证据验证失败 → REVIEW（手册 #32）
                    status = item.status
                    if not verified and status in (RuleStatus.PASS, RuleStatus.FAIL):
                        status = RuleStatus.REVIEW
                        reason = f"{item.reason} [evidence_verified=false]"
                    else:
                        reason = item.reason
                    ev = RuleEvaluation(
                        rule_code=r.rule_code, rule_name=r.rule_name,
                        rule_type=r.rule_type.value, severity=r.severity.value,
                        weight=r.weight, status=status,
                        confidence=item.confidence, reason=reason,
                        evidence=item.evidence, evidence_verified=verified,
                    )
                evaluations.append(ev)

            # 11. 评分（手册 #33/#34，纯 Python）
            base = self._scoring.score(evaluations)
            base.source_call_key = call.source_call_key
            base.scene_id = call.scene_id
            base.scene_name = call.scene_name
            base.seat_id = call.seat_id
            base.seat_name = call.seat_name
            base.summary = self._build_summary(evaluations)

            perf["total_ms"] = int((time.perf_counter() - start_wall) * 1000)
            base.perf = perf

            # 12. 保存 result + rule_result（手册 #39/#40）
            self._results.save_with_rules(base, task_id)

            # 13. 完成
            final_status = (
                COMPLETED if base.overall_status in (OverallStatus.PASS, OverallStatus.FAIL)
                else REVIEW_REQUIRED if base.overall_status == OverallStatus.REVIEW
                else COMPLETED
            )
            self._tasks.update_stage(task_id, final_status, "COMPLETED")
            logger.info(
                "任务完成 task=%s score=%s status=%s",
                task_id, base.score, base.overall_status.value,
                extra=extra,
            )
            return base

        except Exception as e:
            self._tasks.update_stage(
                task_id, FAILED, "FAILED",
                error_code=type(e).__name__,
                error_message=str(e)[:2000],
            )
            logger.exception("任务失败", extra=extra)
            raise

        finally:
            # 手册 #23：任务结束删除临时录音
            self._recording.cleanup(task_id)

    # ---------- 工具 ----------

    @staticmethod
    def _log_extra(call: CallRecord, stage: str, task_id: int | None = None) -> dict:
        return {
            "task_id": task_id,
            "source_call_key": call.source_call_key,
            "scene_id": call.scene_id,
            "stage": stage,
        }

    def _build_skipped_result(
        self,
        call: CallRecord,
        status: OverallStatus = OverallStatus.SKIPPED,
        error_code: str | None = None,
    ) -> ComplianceResult:
        return ComplianceResult(
            source_call_key=call.source_call_key,
            scene_id=call.scene_id,
            scene_name=call.scene_name,
            seat_id=call.seat_id,
            seat_name=call.seat_name,
            score=-1,
            overall_status=status,
            summary=error_code or "",
            error_code=error_code,
        )

    @staticmethod
    def _build_summary(evaluations: list[RuleEvaluation]) -> str:
        parts = []
        for e in evaluations:
            parts.append(f"{e.rule_code}:{e.status.value}")
        return ";".join(parts)


def _find_result(model_resp, rule_code: str):
    """在 LLM 返回结果中查找指定规则。"""
    for r in model_resp.rule_results:
        if r.rule_code == rule_code:
            return r
    return None


def _scenario_of(call: CallRecord):
    """由 CallRecord 构造 MarketingScenario（scene_id/scene_name 来自源表，禁止 LLM 猜测）。"""
    from ..domain.scenario import MarketingScenario

    return MarketingScenario(
        source_scene_id=call.scene_id,
        scene_name=call.scene_name,
    )
