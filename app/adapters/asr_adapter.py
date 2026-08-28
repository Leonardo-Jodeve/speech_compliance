"""
ASR Adapter（手册 #2.1/#21/#22）。

调用链（沿用参考 asr_api_invoke.py）：
    /v1/files/upload              → file_id
    /v1/chat-messages/{agent_id}  → blocking 智能体 → answer

改进：
- 超时与重试次数全部配置化（手册 #22），不写死；
- 可重试：timeout / connection reset / 429 / 502 / 503 / 504；
- 不可重试：401 / 403 / 音频格式不支持 / 文件不存在 / 业务参数错误；
- 由外部传入 Semaphore 限制并发（手册 #43）。
"""
from __future__ import annotations

import os
import time
from mimetypes import guess_type
from pathlib import Path

import httpx

from ..config.logging import get_logger
from ..domain.transcript import Transcript

logger = get_logger(__name__)

SUPPORTED_FORMATS = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}

RETRYABLE_STATUS = {429, 502, 503, 504}


class AsrError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AsrAdapter:
    """内网 ASR 转写适配器。"""

    def __init__(
        self,
        upload_url: str,
        recognize_url: str,
        authorization: str,
        staff_token: str,
        *,
        upload_timeout_seconds: float = 60.0,
        recognition_timeout_seconds: float = 180.0,
        max_retries: int = 2,
        user: str = "admin",
        query: str = "请将该音频完整转换为文本。\n要求：\n1. 尽可能忠实转写；\n2. 不总结；\n3. 不评价；\n4. 不解释；\n5. 不补充录音中不存在的内容；\n6. 只输出转写文本。",
        semaphore: "threading.Semaphore | None" = None,
    ) -> None:
        self._upload_url = upload_url
        self._recognize_url = recognize_url
        self._authorization = authorization
        self._staff_token = staff_token
        self._upload_timeout = upload_timeout_seconds
        self._recognition_timeout = recognition_timeout_seconds
        self._max_retries = max_retries
        self._user = user
        self._query = query
        self._semaphore = semaphore
        self._client = httpx.Client(timeout=max(upload_timeout_seconds, recognition_timeout_seconds) + 10)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._authorization}",
            "Znt-Staff-Code": self._staff_token,
        }

    def transcribe(self, local_audio_path: str, task_id: int = 0) -> Transcript:
        """完整转写：上传 → 识别 → Transcript（手册 #21）。"""
        path = Path(local_audio_path)
        if not path.is_file():
            raise AsrError(f"音频文件不存在: {path}", retryable=False)

        ext = path.suffix.lstrip(".").lower()
        if ext not in SUPPORTED_FORMATS:
            raise AsrError(
                f"不支持的音频格式: {ext}，支持: {', '.join(sorted(SUPPORTED_FORMATS))}",
                retryable=False,
            )

        if self._semaphore is not None:
            self._semaphore.acquire()
        try:
            file_id = self._upload(path)
            return self._recognize(file_id, task_id)
        finally:
            if self._semaphore is not None:
                self._semaphore.release()

    # ---------- 上传 ----------

    def _upload(self, path: Path) -> str:
        mime_type, _ = guess_type(str(path))
        last_error: AsrError | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f, mime_type or "audio/mpeg"),
                        "user": (None, self._user),
                    }
                    resp = self._client.post(
                        self._upload_url,
                        headers=self._headers(),
                        files=files,
                        timeout=self._upload_timeout,
                    )
                if resp.status_code in RETRYABLE_STATUS:
                    raise AsrError(f"上传 HTTP {resp.status_code}", retryable=True)
                if resp.status_code in (401, 403):
                    raise AsrError(f"上传鉴权失败 HTTP {resp.status_code}", retryable=False)
                resp.raise_for_status()
                return resp.json()["id"]
            except AsrError as e:
                last_error = e
                if attempt < self._max_retries and e.retryable:
                    time.sleep(min(2 * attempt, 30))
                    continue
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                last_error = AsrError(f"上传网络异常: {e}", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(min(2 * attempt, 30))
                    continue
                raise last_error from e
            except Exception as e:  # noqa: BLE001
                raise AsrError(f"上传未知异常: {e}", retryable=False) from e
        raise AsrError(f"上传失败: {last_error}")

    # ---------- 识别 ----------

    def _recognize(self, file_id: str, task_id: int) -> Transcript:
        payload = {
            "input_data": {
                "audio_file": {
                    "transfer_method": "local_file",
                    "upload_file_id": file_id,
                    "type": "audio",
                }
            },
            "query": self._query,
            "mode": "blocking",
            "conversation_id": "",
            "user": self._user,
            "files": [],
        }
        last_error: AsrError | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.post(
                    self._recognize_url,
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json=payload,
                    timeout=self._recognition_timeout,
                )
                if resp.status_code in RETRYABLE_STATUS:
                    raise AsrError(f"识别 HTTP {resp.status_code}", retryable=True)
                if resp.status_code in (401, 403):
                    raise AsrError(f"识别鉴权失败 HTTP {resp.status_code}", retryable=False)
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("answer", "") or ""
                if not answer.strip():
                    raise AsrError("ASR 返回空文本", retryable=True)
                return Transcript(
                    text=answer.strip(),
                    asr_file_id=file_id,
                    raw_answer=answer,
                )
            except AsrError as e:
                last_error = e
                if attempt < self._max_retries and e.retryable:
                    time.sleep(min(2 * attempt, 30))
                    continue
                raise
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                last_error = AsrError(f"识别网络异常: {e}", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(min(2 * attempt, 30))
                    continue
                raise last_error from e
            except Exception as e:  # noqa: BLE001
                raise AsrError(f"识别未知异常: {e}", retryable=False) from e
        raise last_error if last_error else AsrError("识别失败")