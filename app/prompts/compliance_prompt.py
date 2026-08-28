"""
合规质检 Prompt 构建（手册 #27）。

System Prompt 固定 10 条原则；User 内容由营销场景 + 规则 JSON + ASR 转写组成。
"""
from __future__ import annotations

import json

SYSTEM_PROMPT = """\
你是企业营销通话话术合规质检模型。

你需要根据给定营销场景和规则，检查员工在真实通话中是否遵守各项要求。

原则：
1. 只能判断输入提供的规则。
2. 不得自行增加规则。
3. 不要求员工逐字复述标准话术。
4. 语义等价表达应视为等价。
5. 不得根据常识补充录音中不存在的内容。
6. PASS和FAIL必须基于真实通话内容。
7. 无法可靠判断时返回REVIEW。
8. CONDITIONAL_REQUIRED未触发时返回NOT_APPLICABLE。
9. evidence必须引用输入Transcript中的真实原文。
10. 只返回JSON，不输出Markdown或其他文字。

请严格按照如下 JSON 结构返回（不要输出除 JSON 外的任何内容）：
{
  "rule_results": [
    {
      "rule_code": "规则编码",
      "status": "PASS 或 FAIL 或 NOT_APPLICABLE 或 REVIEW",
      "confidence": 0.0到1.0之间的小数,
      "reason": "判定理由",
      "evidence": ["引用转写原文的证据片段1", "证据片段2"]
    }
  ]
}
"""


def build_user_content(
    scene_id: str,
    scene_name: str,
    rules_json: str,
    transcript: str,
) -> str:
    """构建 User 内容（手册 #27）。"""
    return f"""营销场景：

scene_id:
{scene_id}

scene_name:
{scene_name}

本场景质检规则：

{rules_json}

ASR转写：

{transcript}
"""


def build_messages(
    scene_id: str,
    scene_name: str,
    rules_json: str,
    transcript: str,
) -> list[dict]:
    """组装完整 messages（手册 #27）。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_content(scene_id, scene_name, rules_json, transcript)},
    ]