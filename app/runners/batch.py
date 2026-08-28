"""
批量执行入口（手册 #44/#43/#8）。

用法：
    python -m app.runners.batch \
        --start 2026-05-06 --end 2026-05-07 \
        --scene 90131206 --seat 13373690980 --limit 20

并发：ThreadPoolExecutor（task_workers）+ 两个全局 Semaphore（asr/llm），
防止打爆内网 AI 平台（手册 #43）。失败隔离：单个任务异常不影响其他任务。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ..adapters.call_database_adapter import CallDatabaseAdapter  # noqa: E402
from ..config.logging import get_logger, setup_logging  # noqa: E402
from ..services.container import build_services  # noqa: E402

logger = get_logger(__name__)


def parse_date(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s, "%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量质检")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD（不含）")
    parser.add_argument("--scene", action="append", default=None, help="场景ID（可多次）")
    parser.add_argument("--seat", action="append", default=None, help="席位ID（可多次）")
    parser.add_argument("--limit", type=int, default=20, help="最多处理条数")
    parser.add_argument("--workers", type=int, default=None, help="并发 worker 数（默认取配置）")
    parser.add_argument("--no-gate", action="store_true", help="不过滤质检资格（调试用）")
    args = parser.parse_args(argv)

    setup_logging()

    deps = build_services()
    settings = deps["settings"]
    engine = deps["engine"]

    adapter = CallDatabaseAdapter(
        engine=engine,
        source_schema="sor",
        source_table="dm_eva_feedorder_call_detail",
        min_talk_seconds=settings.min_talk_seconds,
    )

    start_time = parse_date(args.start)
    end_time = parse_date(args.end)

    logger.info("批量任务启动 start=%s end=%s limit=%s", start_time, end_time, args.limit)

    calls = adapter.query_calls(
        start_time=start_time,
        end_time=end_time,
        scene_ids=args.scene,
        seat_ids=args.seat,
        limit=args.limit,
        only_qualifiable=not args.no_gate,
    )
    logger.info("待处理通话 %s 条", len(calls))

    service = deps["compliance_service"]
    workers = args.workers or settings.task_workers
    ok = fail = 0

    if len(calls) <= 1 or workers <= 1:
        for call in calls:
            try:
                result = service.process_call(call)
                ok += 1
                logger.info("处理完成 score=%s status=%s", result.score, result.overall_status.value)
            except Exception as e:  # noqa: BLE001
                fail += 1
                logger.exception("单条处理失败 call=%s", call.source_call_key)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(service.process_call, c): c for c in calls}
            for fut in as_completed(futures):
                call = futures[fut]
                try:
                    result = fut.result()
                    ok += 1
                except Exception:  # noqa: BLE001
                    fail += 1
                    logger.exception("单条处理失败 call=%s", call.source_call_key)

    logger.info("批量完成 成功=%s 失败=%s 总计=%s", ok, fail, len(calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())