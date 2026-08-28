"""ASR 转写领域模型（手册 §2.1 一期约束）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Transcript:
    """一期只保留完整转写文本，不虚构 speaker / 时间戳 / confidence / segment。"""

    text: str
    asr_file_id: str | None = None
    raw_answer: str = ""