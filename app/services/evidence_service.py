"""
Evidence 防幻觉校验（手册 #32）。

第一阶段：规范化文本后包含匹配。
- 允许空格差异、常规标点差异；
- 若 evidence 片段完全找不到，则 evidence_verified = False，
  对应规则自动转 REVIEW（或进入人工复核标记）。
"""
from __future__ import annotations

import re

# 规范化：去除空白、常见标点（全角/半角），全部使用 Unicode 转义避免源码编码问题
_NORM_RE = re.compile(
    r"[\s"
    r"\u3000\u3001\uFF0C\u3002\uFF01\uFF1F\uFF1B\uFF1A"       # 全角空白、顿号、逗号、句号、叹号、问号、分号、冒号
    r"\u201C\u201D\u2018\u2019\uFF08\uFF09\u300A\u300B\u3010\u3011"  # 引号、括号、书名号、方括号
    r",.!?;:'\"()<>\[\]"                                          # 半角标点
    r"\u2026\u2014\uFF0D\u2013\u00B7\uFF5E\uFF5E\uFF5E]+"          # … — - – · ~
)


def normalize(text: str) -> str:
    """归一化文本：去空白、去常规标点。"""
    if not text:
        return ""
    return _NORM_RE.sub("", text)


def evidence_exists_in_transcript(evidence: str, transcript: str) -> bool:
    """判断 evidence 片段是否真实存在于转写文本（规范化包含匹配）。"""
    if not evidence or not transcript:
        return False
    ev = normalize(evidence)
    tr = normalize(transcript)
    if not ev:
        return False
    return ev in tr


def verify_evidence_list(evidence_list: list[str], transcript: str) -> tuple[bool, list[str]]:
    """返回 (是否全部验证通过, 未通过的 evidence 列表)。"""
    if not evidence_list:
        # 无 evidence：REVIEW 状态可接受，PASS/FAIL 视为证据缺失
        return False, []
    missing = [e for e in evidence_list if not evidence_exists_in_transcript(e, transcript)]
    return len(missing) == 0, missing