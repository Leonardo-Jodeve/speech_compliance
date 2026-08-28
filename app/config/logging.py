"""
统一日志配置（手册 #48）：
- 每条业务日志必须能关联 task_id / source_call_key / scene_id / stage；
- 禁止在 INFO 日志打印：完整手机号、完整 Transcript、Authorization、API Key、数据库密码。
"""
from __future__ import annotations

import logging
import logging.config
import sys
from typing import Any

from .settings import get_settings

_DEFAULT_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "task=%(task_id)s call=%(source_call_key)s scene=%(scene_id)s stage=%(stage)s | %(message)s"
)


class DefaultsFilter(logging.Filter):
    """为缺失的日志上下文填充默认值，避免格式串报错。"""

    def filter(self, record: logging.LogRecord) -> bool:
        for attr in ("task_id", "source_call_key", "scene_id", "stage"):
            if not hasattr(record, attr):
                setattr(record, attr, "-")
        return True



class MaskingFilter(logging.Filter):
    """对日志记录中的敏感字段进行脱敏处理。"""

    SENSITIVE_KEYS = (
        "authorization",
        "api_key",
        "password",
        "staff_token",
        "token",
        "secret",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # 对 extra 中可能出现敏感名称的字段直接脱敏
        for key in list(record.__dict__.keys()):
            if key.lower() in self.SENSITIVE_KEYS and isinstance(record.__dict__[key], str):
                record.__dict__[key] = "******"
        # 消息中的 url 可能携带敏感 query
        msg = record.getMessage()
        if "Authorization" in msg or "api_key=" in msg or "password=" in msg:
            record.msg = "[sensitive message masked]"
            record.args = ()
        return True


def _defaults(record: logging.LogRecord) -> None:
    """为缺失的日志上下文填充默认值，避免格式串报错。"""
    for attr in ("task_id", "source_call_key", "scene_id", "stage"):
        if not hasattr(record, attr):
            setattr(record, attr, "-")


def setup_logging(settings: Any = None) -> None:
    if settings is None:
        try:
            settings = get_settings()
        except Exception:
            settings = None
    level = (settings.log_level if settings else None) or "INFO"
    fmt = (settings.log_format if settings else None) or _DEFAULT_FORMAT

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "masking": {"()": MaskingFilter},
            "defaults": {"()": DefaultsFilter},
        },
        "formatters": {
            "standard": {"format": fmt},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "standard",
                "filters": ["masking", "defaults"],
                "stream": sys.stdout,
            },
        },
        "root": {
            "level": level,
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """获取带默认上下文的 logger。用法：
    logger = get_logger(__name__)
    logger.info("ASR completed", extra={"task_id": ..., "source_call_key": ..., "scene_id": ..., "stage": "ASR"})
    """
    return logging.getLogger(name)