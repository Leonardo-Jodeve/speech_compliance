"""
单条调试入口（手册 #45）。

用法：
    python -m app.runners.single \
        --start 2026-05-06 --end 2026-05-07 \
        --scene 90131206 --limit 1

打印：
通话基本信息 / 营销场景 / 通话时长 / ASR结果 / 加载规则数量 /
每条规则判断 / 最终得分 / ASR耗时 / LLM耗时 / 总耗时。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ..adapters.call_database_adapter import CallDatabaseAdapter  # noqa: E402
from ..config.logging import get_logger, setup_logging  # noqa: E402
from ..services.container import build_services  # noqa: E402

logger = get_logger(__name__)


def parse_date(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s, "%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单条通话质检调试")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD（不含）")
    parser.add_argument("--scene", action="append", default=None, help="场景ID（可多次）")
    parser.add_argument("--seat", action="append", default=None, help="席位ID（可多次）")
    parser.add_argument("--limit", type=int, default=1, help="最多处理条数")
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

    calls = adapter.query_calls(
        start_time=parse_date(args.start),
        end_time=parse_date(args.end),
        scene_ids=args.scene,
        seat_ids=args.seat,
        limit=args.limit,
        only_qualifiable=not args.no_gate,
    )
    if not calls:
        print("未找到符合条件的通话")
        return 1

    call = calls[0]
    print("=" * 70)
    print("通话基本信息")
    print(f"  source_call_key : {call.source_call_key}")
    print(f"  order_id        : {call.order_id}")
    print(f"  seat_id/name    : {call.seat_id} / {call.seat_name}")
    print(f"  start_time      : {call.start_time}")
    print(f"  通话时长        : {call.talk_seconds}s")
    print(f"  call_result     : {call.call_result}")
    print("=" * 70)
    print("营销场景")
    print(f"  scene_id        : {call.scene_id}")
    print(f"  scene_name      : {call.scene_name}")
    print("=" * 70)

    rules = deps["rule_repo"].get_rules_for_call(call.scene_id, call.start_time)
    print(f"加载规则数量: {len(rules)}")
    for r in rules:
        print(f"  - {r.rule_code} [{r.rule_type.value}] {r.rule_name}")

    t0 = time.perf_counter()
    try:
        result = deps["compliance_service"].process_call(call)
    except Exception as e:  # noqa: BLE001
        print(f"处理失败: {e}")
        return 1
    total = time.perf_counter() - t0

    print("=" * 70)
    print("ASR结果")
    print("  （已保存至 qc_transcript，此处仅提示）")
    print("=" * 70)
    print("每条规则判断")
    for e in result.rule_results:
        print(
            f"  {e.rule_code}: {e.status.value} "
            f"(confidence={e.confidence}, verified={e.evidence_verified})"
        )
        print(f"    理由: {e.reason[:120]}")
        if e.evidence:
            print(f"    证据: {e.evidence[:3]}")
    print("=" * 70)
    print(f"最终得分: {result.score}  状态: {result.overall_status.value}")
    print(f"总耗时: {total:.2f}s")
    if result.perf:
        print(
            f"  audio_download_ms={result.perf.get('audio_download_ms')} "
            f"asr_ms={result.perf.get('asr_ms')} llm_ms={result.perf.get('llm_ms')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())