"""
录音下载 Adapter（手册 #23）。

- 流式写文件，禁止一次将整个文件放入内存；
- 下载到 {tmp_root}/{task_id}/ 目录；
- 下载失败支持重试（可重试：timeout / connection reset / 429 / 502 / 503 / 504）；
- 提供 cleanup() 任务结束删除临时录音。
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import httpx

from ..config.logging import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS = {429, 502, 503, 504}


class RecordingDownloadError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class RecordingAdapter:
    def __init__(
        self,
        tmp_root: str = "/data/speech_qc/tmp",
        *,
        download_timeout_seconds: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._tmp_root = Path(tmp_root)
        self._timeout = download_timeout_seconds
        self._max_retries = max_retries
        self._client = client or httpx.Client(timeout=download_timeout_seconds, follow_redirects=True)

    def _task_dir(self, task_id: int) -> Path:
        d = self._tmp_root / str(task_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def download(self, url: str, task_id: int, ext: str = "audio") -> Path:
        """流式下载录音到 {tmp_root}/{task_id}/recording.<ext>，返回本地路径。"""
        if not url or not str(url).strip():
            raise RecordingDownloadError("录音 URL 为空")

        task_dir = self._task_dir(task_id)
        safe_ext = "".join(c for c in str(ext) if c.isalnum())[:10] or "audio"
        dest = task_dir / f"recording.{safe_ext}"

        last_error: RecordingDownloadError | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return self._download_once(url, dest)
            except RecordingDownloadError as e:
                last_error = e
                if attempt < self._max_retries and e.retryable:
                    wait = min(2 * attempt, 30)
                    logger.warning(
                        "录音下载重试 attempt=%s/%s wait=%ss reason=%s",
                        attempt, self._max_retries, wait, e,
                        extra={"task_id": str(task_id), "source_call_key": None,
                               "scene_id": None, "stage": "DOWNLOAD"},
                    )
                    time.sleep(wait)
                    continue
                break

        raise RecordingDownloadError(
            f"录音下载失败(重试{self._max_retries}次): {last_error}"
        )

    def _download_once(self, url: str, dest: Path) -> Path:
        retryable = False
        try:
            with self._client.stream("GET", url) as resp:
                if resp.status_code in RETRYABLE_STATUS:
                    raise RecordingDownloadError(
                        f"HTTP {resp.status_code}（可重试）", retryable=True,
                    )
                if resp.status_code >= 400:
                    raise RecordingDownloadError(
                        f"HTTP {resp.status_code} 下载失败", retryable=False,
                    )
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                os.replace(tmp, dest)
                return dest
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            raise RecordingDownloadError(f"网络异常: {e}", retryable=True) from e
        except RecordingDownloadError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RecordingDownloadError(f"未知异常: {e}", retryable=retryable) from e

    def cleanup(self, task_id: int) -> None:
        """任务结束删除临时录音目录（手册 #23：必须 try/finally）。"""
        d = self._tmp_root / str(task_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            logger.info(
                "已清理临时录音目录",
                extra={"task_id": str(task_id), "source_call_key": None,
                       "scene_id": None, "stage": "CLEANUP"},
            )