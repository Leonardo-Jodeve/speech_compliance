"""
数据库迁移 001：创建规则系统与质检任务/结果表（手册 #14-#20、#35-#40）。

用法：
    python migrations/001_create_tables.py                # 使用 config.yaml 的数据库配置
    python migrations/001_create_tables.py --schema qc    # 指定 schema
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config.settings import load_config  # noqa: E402


def build_ddl(schema: str) -> list[str]:
    """构造完整 DDL 语句列表（每条以分号结尾，按 ; 分割执行）。"""
    s = schema
    raw = f"""
CREATE TABLE IF NOT EXISTS {s}.qc_scene (
    id              BIGSERIAL PRIMARY KEY,
    source_scene_id VARCHAR(64)  NOT NULL UNIQUE,
    scene_name      VARCHAR(200) NOT NULL,
    description     TEXT,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {s}.qc_rule (
    id                  BIGSERIAL PRIMARY KEY,
    rule_code           VARCHAR(128) NOT NULL UNIQUE,
    rule_name           VARCHAR(200) NOT NULL,
    rule_type           VARCHAR(32)  NOT NULL DEFAULT 'REQUIRED'
                        CHECK (rule_type IN ('REQUIRED','FORBIDDEN','CONDITIONAL_REQUIRED')),
    description         TEXT,
    standard_expression TEXT,
    judge_instruction   TEXT,
    severity            VARCHAR(16)  NOT NULL DEFAULT 'MEDIUM'
                        CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    weight              NUMERIC(6,2) NOT NULL DEFAULT 10,
    effective_from      TIMESTAMPTZ,
    effective_to        TIMESTAMPTZ,
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    revision_id         VARCHAR(64),
    content_hash        VARCHAR(64),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS {s}.qc_scene_rule (
    id              BIGSERIAL PRIMARY KEY,
    scene_id        BIGINT NOT NULL REFERENCES {s}.qc_scene(id) ON DELETE CASCADE,
    rule_id         BIGINT NOT NULL REFERENCES {s}.qc_rule(id)  ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    weight_override NUMERIC(5,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scene_id, rule_id)
);
CREATE INDEX IF NOT EXISTS idx_qc_scene_rule_scene ON {s}.qc_scene_rule(scene_id);

CREATE TABLE IF NOT EXISTS {s}.qc_task (
    id              BIGSERIAL PRIMARY KEY,
    source_call_key VARCHAR(64)  NOT NULL UNIQUE,
    order_id        VARCHAR(64),
    scene_id        VARCHAR(64),
    scene_name      VARCHAR(200),
    seat_id         VARCHAR(64),
    seat_name       VARCHAR(200),
    recording_url   TEXT,
    status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    current_stage   VARCHAR(32),
    retry_count     INT          NOT NULL DEFAULT 0,
    error_code      VARCHAR(64),
    error_message   TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_qc_task_status  ON {s}.qc_task(status);
CREATE INDEX IF NOT EXISTS idx_qc_task_scene   ON {s}.qc_task(scene_id);
CREATE INDEX IF NOT EXISTS idx_qc_task_created ON {s}.qc_task(created_at);

CREATE TABLE IF NOT EXISTS {s}.qc_transcript (
    id              BIGSERIAL PRIMARY KEY,
    task_id         BIGINT NOT NULL REFERENCES {s}.qc_task(id) ON DELETE CASCADE,
    source_call_key VARCHAR(64) NOT NULL,
    asr_file_id     VARCHAR(128),
    transcript_text TEXT,
    raw_answer      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id)
);

CREATE TABLE IF NOT EXISTS {s}.qc_result (
    id                   BIGSERIAL PRIMARY KEY,
    task_id              BIGINT NOT NULL REFERENCES {s}.qc_task(id) ON DELETE CASCADE,
    source_call_key      VARCHAR(64) NOT NULL,
    scene_id             VARCHAR(64),
    scene_name           VARCHAR(200),
    seat_id              VARCHAR(64),
    seat_name            VARCHAR(200),
    score                NUMERIC(5,2) NOT NULL,
    overall_status       VARCHAR(32)  NOT NULL,
    total_rules          INT NOT NULL DEFAULT 0,
    passed_rules         INT NOT NULL DEFAULT 0,
    failed_rules         INT NOT NULL DEFAULT 0,
    review_rules         INT NOT NULL DEFAULT 0,
    not_applicable_rules INT NOT NULL DEFAULT 0,
    summary              TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id)
);
CREATE INDEX IF NOT EXISTS idx_qc_result_call  ON {s}.qc_result(source_call_key);
CREATE INDEX IF NOT EXISTS idx_qc_result_scene ON {s}.qc_result(scene_id);

CREATE TABLE IF NOT EXISTS {s}.qc_rule_result (
    id                BIGSERIAL PRIMARY KEY,
    result_id         BIGINT NOT NULL REFERENCES {s}.qc_result(id) ON DELETE CASCADE,
    rule_code         VARCHAR(128) NOT NULL,
    rule_name         VARCHAR(200),
    rule_type         VARCHAR(32),
    severity          VARCHAR(16),
    weight            NUMERIC(5,2),
    status            VARCHAR(32) NOT NULL,
    confidence        NUMERIC(5,4),
    reason            TEXT,
    evidence_json     TEXT,
    evidence_verified BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qc_rule_result_code   ON {s}.qc_rule_result(rule_code);
CREATE INDEX IF NOT EXISTS idx_qc_rule_result_result ON {s}.qc_rule_result(result_id);
"""
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="创建质检系统表")
    parser.add_argument("--schema", default=None, help="目标 schema（默认取配置 db_schema，其次 public）")
    args = parser.parse_args()

    cfg = load_config()
    dsn = (
        f"postgresql://{cfg.db_username}:{cfg.db_password}"
        f"@{cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
    )
    schema = args.schema or cfg.db_schema or "public"

    engine = create_engine(dsn)
    with engine.connect() as conn:
        # conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        # conn.commit()
        statements = [s.strip() for s in build_ddl(schema).split(";") if s.strip()]
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()
    engine.dispose()
    print(f"迁移 001 完成：schema={schema}")


if __name__ == "__main__":
    main()