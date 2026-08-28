"""
依赖组装（Composition Root）。

根据配置构建：
- 数据库 Engine
- 各 Repository
- 各 Adapter（ASR / TokenHub / Recording）
- ScoringService / ComplianceTaskService
"""
from __future__ import annotations

import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ..adapters.asr_adapter import AsrAdapter
from ..adapters.recording_adapter import RecordingAdapter
from ..adapters.tokenhub_adapter import LlmAdapter, TokenHubClientFactory
from ..config.settings import Settings, get_settings
from ..repositories.result_repository import ResultRepository, TranscriptRepository
from ..repositories.rule_repository import RuleRepository
from ..repositories.task_repository import TaskRepository
from ..services.compliance_service import ComplianceTaskService
from ..services.scoring_service import ScoringService


def build_engine(settings: Settings) -> Engine:
    dsn = (
        f"postgresql://{settings.db_username}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    return create_engine(dsn, pool_pre_ping=True)


def build_asr_semaphore(settings: Settings) -> threading.Semaphore:
    return threading.Semaphore(settings.asr_max_concurrency)


def build_llm_semaphore(settings: Settings) -> threading.Semaphore:
    return threading.Semaphore(settings.llm_max_concurrency)


def build_services(settings: Settings | None = None) -> dict:
    """构建全部依赖，返回容器字典。"""
    settings = settings or get_settings()
    engine = build_engine(settings)

    schema = settings.db_schema or "public"

    task_repo = TaskRepository(engine, schema=schema)
    transcript_repo = TranscriptRepository(engine, schema=schema)
    result_repo = ResultRepository(engine, schema=schema)
    rule_repo = RuleRepository(engine, schema=schema)

    asr_semaphore = build_asr_semaphore(settings)
    llm_semaphore = build_llm_semaphore(settings)

    asr_adapter = AsrAdapter(
        settings.asr_upload_url,
        settings.asr_recognize_url,
        settings.asr_authorization,
        settings.asr_staff_token,
        upload_timeout_seconds=settings.asr_upload_timeout_seconds,
        recognition_timeout_seconds=settings.asr_recognition_timeout_seconds,
        max_retries=settings.asr_max_retries,
        user=settings.asr_user,
        query=settings.asr_query,
        semaphore=asr_semaphore,
    )

    tokenhub_factory = TokenHubClientFactory(
        settings.tokenhub_base_url,
        settings.tokenhub_api_key,
    )
    llm_adapter = LlmAdapter(
        tokenhub_factory,
        model=settings.tokenhub_model,
        temperature=settings.tokenhub_temperature,
        timeout_seconds=settings.tokenhub_timeout_seconds,
        max_retries=settings.tokenhub_max_retries,
        semaphore=llm_semaphore,
    )

    recording_adapter = RecordingAdapter(
        settings.recording_tmp_root,
        download_timeout_seconds=settings.recording_download_timeout_seconds,
        max_retries=settings.recording_max_retries,
    )

    scoring_service = ScoringService(pass_score=settings.pass_score)

    compliance_service = ComplianceTaskService(
        engine=engine,
        task_repo=task_repo,
        transcript_repo=transcript_repo,
        result_repo=result_repo,
        rule_repo=rule_repo,
        asr_adapter=asr_adapter,
        llm_adapter=llm_adapter,
        recording_adapter=recording_adapter,
        scoring_service=scoring_service,
        min_talk_seconds=settings.min_talk_seconds,
        no_rule_behavior=settings.no_rule_behavior,
        schema=schema,
    )

    return {
        "settings": settings,
        "engine": engine,
        "task_repo": task_repo,
        "transcript_repo": transcript_repo,
        "result_repo": result_repo,
        "rule_repo": rule_repo,
        "asr_adapter": asr_adapter,
        "llm_adapter": llm_adapter,
        "recording_adapter": recording_adapter,
        "scoring_service": scoring_service,
        "compliance_service": compliance_service,
    }


class ContainerComposition:
    """组装后的依赖容器（简单字典包装）。"""

    def __init__(self, deps: dict) -> None:
        self._deps = deps

    def __getattr__(self, name: str):
        if name in self._deps:
            return self._deps[name]
        raise AttributeError(name)