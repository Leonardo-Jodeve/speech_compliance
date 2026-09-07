"""
质检任务 Repository（手册 #36/#37）。

qc_task 表保存每个通话的处理状态与阶段，UNIQUE(source_call_key) 保证幂等。
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config.logging import get_logger

logger = get_logger(__name__)

# 任务状态（手册 #37）
PENDING = "PENDING"
DOWNLOADING = "DOWNLOADING"
ASR_PROCESSING = "ASR_PROCESSING"
ASR_COMPLETED = "ASR_COMPLETED"
LLM_PROCESSING = "LLM_PROCESSING"
COMPLETED = "COMPLETED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
FAILED = "FAILED"
SKIPPED = "SKIPPED"


class TaskRepository:
    """qc_task 表操作（幂等：UNIQUE(source_call_key)）。"""

    def __init__(self, engine: Engine, schema: str = "public") -> None:
        self._engine = engine
        self._schema = schema

    def _t(self, table: str) -> str:
        """返回带 schema 前缀的表名；schema 为空时直接用表名（测试用）。"""
        return f"{self._schema}.{table}" if self._schema else table

    def create_task(
        self,
        source_call_key: str,
        order_id: str | None,
        scene_id: str,
        scene_name: str,
        seat_id: str | None,
        seat_name: str | None,
        recording_url: str | None,
    ) -> int | None:
        """创建任务，返回 task_id；若已存在（幂等）返回已有 task_id。

        手册 #36：UNIQUE(source_call_key) 保证同一通话只产生一份质检记录（Test 12）。

        实现说明：
        - 先查后插：已存在直接返回既有 id（SQLite 与 PostgreSQL 均兼容）；
        - 并发兜底：INSERT 使用 ON CONFLICT DO NOTHING，冲突时返回空行，
          此时再查询一次返回既有 id（PostgreSQL 语义）。
        """
        # 1) 幂等：已存在则直接返回既有 id
        existing = self._find_by_key(source_call_key)
        if existing is not None:
            # 非终态任务可刷新为 PENDING（终态 COMPLETED/SKIPPED/REVIEW_REQUIRED 不动）
            if existing["status"] not in (COMPLETED, REVIEW_REQUIRED, SKIPPED):
                with self._engine.begin() as conn:
                    conn.execute(text(
                        f"UPDATE {self._t('qc_task')} SET status=:status, current_stage=:status, "
                        "retry_count=retry_count+1, error_code=NULL, error_message=NULL, "
                        "started_at=NULL, finished_at=NULL WHERE id=:id"
                    ), {"status": PENDING, "id": existing["id"]})
            return existing["id"]

        # 2) 不存在：INSERT（ON CONFLICT 仅作并发兜底）
        sql = text(
            f"""
            INSERT INTO {self._t('qc_task')}
                (source_call_key, order_id, scene_id, scene_name,
                 seat_id, seat_name, recording_url, status, current_stage, retry_count)
            VALUES
                (:source_call_key, :order_id, :scene_id, :scene_name,
                 :seat_id, :seat_name, :recording_url, :status, :stage, 0)
            ON CONFLICT (source_call_key) DO NOTHING
            RETURNING id
            """
        )
        params = {
            "source_call_key": source_call_key,
            "order_id": order_id,
            "scene_id": scene_id,
            "scene_name": scene_name,
            "seat_id": seat_id,
            "seat_name": seat_name,
            "recording_url": recording_url,
            "status": PENDING,
            "stage": PENDING,
        }
        with self._engine.begin() as conn:
            row = conn.execute(sql, params).mappings().first()
        if row is not None:
            return row["id"]
        # 并发冲突：其他线程已插入，返回既有 id
        existing = self._find_by_key(source_call_key)
        return existing["id"] if existing else None

    def _find_by_key(self, source_call_key: str) -> dict | None:
        sql = text(
            f"SELECT id, status FROM {self._t('qc_task')} WHERE source_call_key = :key"
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"key": source_call_key}).mappings().first()
        return dict(row) if row else None

    def update_stage(
        self,
        task_id: int,
        status: str,
        stage: str,
        *,
        retry_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        sets = ["status = :status", "current_stage = :stage"]
        params: dict = {"id": task_id, "status": status, "stage": stage}

        if retry_count is not None:
            sets.append("retry_count = :retry_count")
            params["retry_count"] = retry_count
        if error_code is not None:
            sets.append("error_code = :error_code")
            params["error_code"] = error_code
        if error_message is not None:
            sets.append("error_message = :error_message")
            params["error_message"] = error_message

        if status in (COMPLETED, FAILED, SKIPPED, REVIEW_REQUIRED):
            sets.append("finished_at = CURRENT_TIMESTAMP")
        if stage != PENDING:
            sets.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")

        sql = text(
            f"UPDATE {self._t('qc_task')} SET {', '.join(sets)} WHERE id = :id"
        )
        with self._engine.begin() as conn:
            conn.execute(sql, params)

    def mark_failed(
        self,
        task_id: int,
        stage: str,
        error_code: str,
        error_message: str,
    ) -> None:
        self.update_stage(task_id, FAILED, stage, error_code=error_code, error_message=error_message)

    def get_task(self, task_id: int) -> dict | None:
        sql = text(
            f"SELECT * FROM {self._t('qc_task')} WHERE id = :id"
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"id": task_id}).mappings().first()
        return dict(row) if row else None

    def task_exists(self, source_call_key: str) -> bool:
        """是否已存在该通话任务（幂等检查）。"""
        sql = text(
            f"SELECT 1 FROM {self._t('qc_task')} WHERE source_call_key = :key"
        )
        with self._engine.connect() as conn:
            return conn.execute(sql, {"key": source_call_key}).first() is not None

    def get_completed_task(self, source_call_key: str) -> dict | None:
        """已完结（COMPLETED / REVIEW_REQUIRED / SKIPPED）的任务，用于幂等跳过。"""
        sql = text(
            f"SELECT * FROM {self._t('qc_task')} "
            f"WHERE source_call_key = :key AND status IN ('COMPLETED','REVIEW_REQUIRED','SKIPPED')"
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"key": source_call_key}).mappings().first()
        return dict(row) if row else None
