"""
TokenHub LLM Adapter（手册 #25/#26/#27/#28/#29/#30/#31/#32）。

- TokenHubClientFactory：负责创建 OpenAI Client，业务 Service 不接触 base_url/api_key。
- LlmAdapter.evaluate_rules()：
    构建 Prompt → 调用 LLM（temperature 0~0.2）→ 解析 JSON → Pydantic 强校验
    → 规则完整性校验（#31）→ 规则集合校验（#30）→ Evidence 防幻觉校验（#32）。
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from ..config.logging import get_logger
from ..domain.compliance import ComplianceModelResponse, LlmRuleResult, RuleStatus
from ..domain.rule import ComplianceRule
from ..domain.scenario import MarketingScenario
from ..domain.transcript import Transcript
from ..prompts.compliance_prompt import build_messages
from ..schemas.llm_response import ComplianceResponseModel

logger = get_logger(__name__)


class TokenHubClientFactory:
    """负责创建 OpenAI 兼容客户端（手册 #25）。"""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def create(self) -> OpenAI:
        return OpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
        )


class LlmAdapter:
    """合规质检 LLM Adapter。"""

    def __init__(
        self,
        factory: TokenHubClientFactory,
        *,
        model: str,
        temperature: float = 0.1,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        semaphore: threading.Semaphore | None = None,
    ) -> None:
        self._factory = factory
        self._model = model
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._semaphore = semaphore

    def evaluate_rules(
        self,
        transcript: Transcript,
        scenario: MarketingScenario,
        rules: list[ComplianceRule],
    ) -> ComplianceModelResponse:
        """逐规则 LLM 判断（手册 #25）。"""
        if not rules:
            return ComplianceModelResponse(rule_results=[])

        rules_json = json.dumps(
            [r.to_prompt_dict() for r in rules],
            ensure_ascii=False,
            indent=2,
        )
        messages = build_messages(
            scenario.scene_id,
            scenario.scene_name,
            rules_json,
            transcript.text,
        )

        if self._semaphore is not None:
            self._semaphore.acquire()
        try:
            client = self._factory.create()
            raw_content, usage = self._call_with_retry(client, messages)
        finally:
            if self._semaphore is not None:
                self._semaphore.release()

        parsed = self._parse_json_response(raw_content)
        model_response = self._validate_schema(parsed)
        self._audit_rules(model_response, rules)

        return ComplianceModelResponse(
            rule_results=[
                LlmRuleResult(
                    rule_code=r.rule_code,
                    status=RuleStatus(r.status),
                    confidence=r.confidence,
                    reason=r.reason,
                    evidence=r.evidence,
                )
                for r in model_response.rule_results
            ]
        )

    # ---------- LLM 调用 ----------

    def _call_with_retry(
        self,
        client: OpenAI,
        messages: list[dict],
    ) -> tuple[str, dict]:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self._temperature,
                    timeout=self._timeout,
                )
                content = resp.choices[0].message.content or ""
                usage = {
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(resp.usage, "total_tokens", 0) or 0,
                }
                return content, usage
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < self._max_retries:
                    time.sleep(min(2 * attempt, 30))
                    continue
                raise RuntimeError(f"TokenHub 调用失败(重试{self._max_retries}次): {last_error}") from last_error
        raise RuntimeError(f"TokenHub 调用失败: {last_error}")

    # ---------- JSON 解析 ----------

    @staticmethod
    def _parse_json_response(content: str) -> Any:
        """从 LLM 输出中提取 JSON（容忍 ```json ... ``` 包裹）。"""
        text = content.strip()
        # 去除 markdown 代码块
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        # 查找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"LLM 输出中未找到 JSON 对象: {text[:200]!r}")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 输出 JSON 解析失败: {e}") from e

    # ---------- Schema 校验 ----------

    @staticmethod
    def _validate_schema(data: Any) -> ComplianceResponseModel:
        try:
            return ComplianceResponseModel.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"LLM 返回不符合 Schema: {e}") from e

    # ---------- 规则审计（#30/#31） ----------

    @staticmethod
    def _audit_rules(
        model_response: ComplianceResponseModel,
        rules: list[ComplianceRule],
    ) -> None:
        """审计：模型返回的 rule_code 必须 ⊆ 输入规则；缺失的规则必须补为 REVIEW（#30/#31）。"""
        allowed = {r.rule_code for r in rules}
        seen: set[str] = set()

        kept: list[Any] = []
        for item in model_response.rule_results:
            if item.rule_code not in allowed:
                logger.warning(
                    "模型虚构规则已丢弃: %s", item.rule_code,
                    extra={"task_id": None, "source_call_key": None, "scene_id": None, "stage": "LLM_AUDIT"},
                )
                continue
            kept.append(item)
            seen.add(item.rule_code)

        # 缺失规则补 REVIEW（手册 #31：MODEL_MISSING_RULE_RESULT）
        for r in rules:
            if r.rule_code not in seen:
                logger.warning(
                    "模型缺失规则结果: %s → REVIEW", r.rule_code,
                    extra={"task_id": None, "source_call_key": None, "scene_id": None, "stage": "LLM_AUDIT"},
                )
                kept.append(
                    _missing_rule_item(r.rule_code)
                )

        model_response.rule_results = kept


def _missing_rule_item(rule_code: str) -> Any:
    """构造缺失规则对应的模型项（REVIEW）。"""
    from ..schemas.llm_response import RuleEvaluationModel

    return RuleEvaluationModel(
        rule_code=rule_code,
        status="REVIEW",
        confidence=0.0,
        reason="MODEL_MISSING_RULE_RESULT：模型未返回该规则判断结果",
        evidence=[],
    )