"""
pytest 共享夹具：
- sqlite 内存引擎（用于 Repository 层测试，避免依赖 PostgreSQL）。
- 注意：生产 DDL 使用 PostgreSQL 方言，单元测试中我们用 sqlite 兼容的最小表结构。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# 确保项目根可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SQLITE_DDL = """
CREATE TABLE qc_scene (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_scene_id  TEXT NOT NULL UNIQUE,
    scene_name       TEXT NOT NULL,
    description      TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE qc_rule (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code           VARCHAR(128) NOT NULL,
    rule_name           VARCHAR(200) NOT NULL,
    rule_type           VARCHAR(32) NOT NULL DEFAULT 'REQUIRED',
    description         TEXT,
    standard_expression TEXT,
    judge_instruction   TEXT,
    severity            VARCHAR(16) NOT NULL DEFAULT 'MEDIUM',
    weight              NUMERIC(6,2) NOT NULL DEFAULT 10,
    effective_from      TIMESTAMP,
    effective_to        TIMESTAMP,
    enabled             INTEGER NOT NULL DEFAULT 1,
    revision_id         VARCHAR(64),
    content_hash        VARCHAR(64),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (rule_code)
);

CREATE TABLE qc_scene_rule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scene_id        INTEGER NOT NULL,
    rule_id         INTEGER NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    weight_override NUMERIC(5,2),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (scene_id, rule_id)
);

CREATE TABLE qc_task (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_call_key VARCHAR(64) NOT NULL,
    order_id        VARCHAR(64),
    scene_id        VARCHAR(64),
    scene_name      VARCHAR(200),
    seat_id         VARCHAR(64),
    seat_name       VARCHAR(200),
    recording_url   TEXT,
    status          VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    current_stage   VARCHAR(32),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    error_code      VARCHAR(64),
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    UNIQUE (source_call_key)
);

CREATE TABLE qc_transcript (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    source_call_key VARCHAR(64) NOT NULL,
    asr_file_id     VARCHAR(128),
    transcript_text TEXT,
    raw_answer      TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (task_id)
);

CREATE TABLE qc_result (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              INTEGER NOT NULL,
    source_call_key      VARCHAR(64) NOT NULL,
    scene_id             VARCHAR(64),
    scene_name           VARCHAR(200),
    seat_id              VARCHAR(64),
    seat_name            VARCHAR(200),
    score                NUMERIC(5,2) NOT NULL,
    overall_status       VARCHAR(32) NOT NULL,
    total_rules          INTEGER NOT NULL DEFAULT 0,
    passed_rules         INTEGER NOT NULL DEFAULT 0,
    failed_rules         INTEGER NOT NULL DEFAULT 0,
    review_rules         INTEGER NOT NULL DEFAULT 0,
    not_applicable_rules INTEGER NOT NULL DEFAULT 0,
    summary              TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (task_id)
);

CREATE TABLE qc_rule_result (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id         INTEGER NOT NULL,
    rule_code         VARCHAR(128) NOT NULL,
    rule_name         VARCHAR(200),
    rule_type         VARCHAR(32),
    severity          VARCHAR(16),
    weight            NUMERIC(5,2),
    status            VARCHAR(32) NOT NULL,
    confidence        NUMERIC(5,4),
    reason            TEXT,
    evidence_json     TEXT,
    evidence_verified INTEGER NOT NULL DEFAULT 1,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        for stmt in SQLITE_DDL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    return eng