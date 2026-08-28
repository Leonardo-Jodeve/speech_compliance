"""
呼叫记录数据库 Adapter（手册 #11/#12/#7）。

改造点：
- 不使用 SELECT *，明确列出字段；
- 不返回 Markdown，返回 list[CallRecord]；
- 所有超大 ID 一律 CAST AS TEXT，禁止精度损失；
- 支持增量查询（时间范围）+ 场景 + 员工 + limit；
- 质检资格过滤配置化（min_talk_seconds 来自配置，不散落 SQL）。
"""
from __future__ import annotations

import datetime as _dt
from typing import Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config.logging import get_logger
from ..domain.call import CallRecord, build_source_call_key

logger = get_logger(__name__)

# 手册 #11 建议的字段清单（全部显式列出，超大 ID CAST AS TEXT）
_BASE_COLUMNS = """
    CAST(latn_id AS TEXT)           AS latn_id,
    CAST(activity_id AS TEXT)       AS activity_id,
    CAST(order_id AS TEXT)          AS order_id,

    CAST(opr_pos_code AS TEXT)      AS opr_pos_code,
    opr_pos_name,

    CAST(act_scene_id AS TEXT)      AS act_scene_id,
    act_scene_name,

    CAST(creator AS TEXT)           AS creator,
    CAST(seat_id AS TEXT)           AS seat_id,
    seat_name,

    CAST(feedback_result AS TEXT)   AS feedback_result,
    CAST(object_id AS TEXT)         AS object_id,

    CAST(main_acc_nbr AS TEXT)      AS main_acc_nbr,
    CAST(host_call_nbr AS TEXT)     AS host_call_nbr,
    CAST(guest_called_nbr AS TEXT)  AS guest_called_nbr,

    start_date,
    end_date,

    call_time,
    call_result,
    file_url,

    CAST(call_source AS TEXT)       AS call_source,
    CAST(call_type AS TEXT)         AS call_type,
    CAST(twoconfir AS TEXT)         AS twoconfir,
    CAST(terminal_type AS TEXT)     AS terminal_type,

    CAST(p_day AS TEXT)             AS p_day,
    answertime
"""


class CallDatabaseAdapter:
    """读取源表 sor.dm_eva_feedorder_call_detail，返回 list[CallRecord]。"""

    def __init__(
        self,
        *,
        source_schema: str = "sor",
        source_table: str = "dm_eva_feedorder_call_detail",
        min_talk_seconds: int = 15,
        engine: Engine | None = None,
    ) -> None:
        self._source_schema = source_schema
        self._source_table = source_table
        self._min_talk_seconds = min_talk_seconds
        self._engine = engine

    # ---------- 行 -> CallRecord ----------

    def _row_to_call(self, row) -> CallRecord:
        start_time = row["start_date"]
        if isinstance(start_time, _dt.datetime):
            pass
        elif isinstance(start_time, _dt.date):
            start_time = _dt.datetime.combine(start_time, _dt.time.min)
        else:
            start_time = None

        end_time = row["end_date"]
        if isinstance(end_time, _dt.datetime):
            pass
        elif isinstance(end_time, _dt.date):
            end_time = _dt.datetime.combine(end_time, _dt.time.min)
        else:
            end_time = None

        order_id = row["order_id"]
        host = row["host_call_nbr"]
        guest = row["guest_called_nbr"]

        source_call_key = build_source_call_key(
            order_id,
            start_time,
            host,
            guest,
        )

        return CallRecord(
            source_call_key=source_call_key,
            latn_id=row["latn_id"],
            activity_id=row["activity_id"],
            order_id=order_id,
            opr_pos_code=row["opr_pos_code"],
            opr_pos_name=row["opr_pos_name"],
            scene_id=row["act_scene_id"] or "",
            scene_name=row["act_scene_name"] or "",
            creator=row["creator"],
            seat_id=row["seat_id"],
            seat_name=row["seat_name"],
            feedback_result=row["feedback_result"],
            object_id=row["object_id"],
            main_acc_nbr=row["main_acc_nbr"],
            host_call_nbr=host,
            guest_called_nbr=guest,
            start_time=start_time,
            end_time=end_time,
            talk_seconds=int(row["call_time"] or 0),
            call_result=row["call_result"] or "",
            recording_url=row["file_url"],
            call_source=row["call_source"],
            call_type=row["call_type"],
            two_confirm=row["twoconfir"],
            terminal_type=row["terminal_type"],
            partition_day=row["p_day"],
            answer_time=row["answertime"],
        )

    # ---------- 主查询 ----------

    def query_calls(
        self,
        start_time: _dt.datetime | None = None,
        end_time: _dt.datetime | None = None,
        scene_ids: Sequence[str] | None = None,
        seat_ids: Sequence[str] | None = None,
        limit: int | None = None,
        *,
        only_qualifiable: bool = True,
    ) -> list[CallRecord]:
        """增量查询通话记录（手册 #12/#45）。

        至少支持 start_time/end_time/scene_ids/limit；
        p_day 为分区或索引字段时同时使用，减少扫描量。
        """
        where: list[str] = []
        params: dict = {}

        if start_time is not None:
            where.append("CAST(start_date AS timestamp) >= :start_time")
            params["start_time"] = start_time
            where.append("p_day >= :start_day")
            params["start_day"] = start_time.strftime("%Y%m%d")

        if end_time is not None:
            where.append("CAST(start_date AS timestamp) < :end_time")
            params["end_time"] = end_time
            where.append("p_day <= :end_day")
            params["end_day"] = end_time.strftime("%Y%m%d")

        if scene_ids:
            where.append("CAST(act_scene_id AS TEXT) = ANY(:scene_ids)")
            params["scene_ids"] = [str(s) for s in scene_ids]

        if seat_ids:
            where.append("CAST(seat_id AS TEXT) = ANY(:seat_ids)")
            params["seat_ids"] = [str(s) for s in seat_ids]

        if only_qualifiable:
            # 手册 #10：call_result='接通' AND file_url 非空 AND call_time >= min_talk_seconds
            where.append("call_result = '接通'")
            where.append("file_url IS NOT NULL")
            where.append("BTRIM(file_url) <> ''")
            where.append("COALESCE(call_time, 0) >= :min_talk_seconds")
            params["min_talk_seconds"] = self._min_talk_seconds

        where_sql = " AND ".join(where) if where else "TRUE"

        sql_text = (
            f"SELECT {_BASE_COLUMNS} "
            f"FROM {self._source_schema}.{self._source_table} "
            f"WHERE {where_sql}"
        )
        if limit is not None:
            sql_text += " LIMIT :limit"
            params["limit"] = int(limit)

        logger.info(
            "query_calls start=%s end=%s scenes=%s seats=%s limit=%s only_qualifiable=%s",
            start_time, end_time, scene_ids, seat_ids, limit, only_qualifiable,
            extra={"task_id": None, "source_call_key": None, "scene_id": None, "stage": "DB"},
        )

        stmt = text(sql_text)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt, params).mappings().all()

        calls = [self._row_to_call(r) for r in rows]
        logger.info(
            "query_calls returned %s rows", len(calls),
            extra={"task_id": None, "source_call_key": None, "scene_id": None, "stage": "DB"},
        )
        return calls