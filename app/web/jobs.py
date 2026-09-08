"""有界本地队列。通话来源仅接受服务端查询快照，不信任浏览器录音 URL。"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from uuid import uuid4

from app.domain.call import CallRecord, build_source_call_key


class QueueError(ValueError):
    pass


class JobManager:
    def __init__(self, service, workers=4, min_talk_seconds=15):
        self.service = service
        self.minimum = min_talk_seconds
        self.pool = ThreadPoolExecutor(max_workers=max(1, min(workers, 20)), thread_name_prefix="qc-web")
        self.lock = Lock()
        self.searches = OrderedDict()
        self.jobs = OrderedDict()
        self.active_keys = set()
        self.closed = False

    def cache_search(self, calls):
        with self.lock:
            expired = [key for key, (expires, _) in self.searches.items() if expires < monotonic()]
            for key in expired:
                del self.searches[key]
            while len(self.searches) >= 100:
                self.searches.popitem(last=False)
            search_id = uuid4().hex
            self.searches[search_id] = (monotonic() + 1800, {c.source_call_key: c for c in calls})
            return search_id

    def submit(self, search_id, keys):
        keys = list(dict.fromkeys(keys))
        with self.lock:
            snapshot = self.searches.get(search_id)
            if not snapshot or snapshot[0] < monotonic():
                raise QueueError("查询已过期，请重新查询通话后再提交")
            calls = snapshot[1]
            if any(key not in calls for key in keys):
                raise QueueError("所选通话不属于本次查询，请重新选择")
            if any(not calls[key].is_qualifiable(self.minimum) for key in keys):
                raise QueueError("所选通话含未接通、缺录音或时长不足的记录")
            if any(key in self.active_keys for key in keys):
                raise QueueError("所选通话正在排队或执行，请等待当前任务完成")
            if self.closed or len(self.active_keys) + len(keys) > 200:
                raise QueueError("当前队列已满或正在关闭，请稍后重试（最多 200 通）")
            while len(self.jobs) >= 100:
                finished = next((key for key, job in self.jobs.items() if all(i["state"] in ("DONE", "FAILED") for i in job["items"])), None)
                if finished is None:
                    raise QueueError("当前批次过多，请等待执行完成")
                del self.jobs[finished]
            job_id = uuid4().hex
            items = [{"key": key, "order_id": calls[key].order_id, "scene_name": calls[key].scene_name,
                      "seat_name": calls[key].seat_name, "state": "QUEUED", "outcome": None, "error": None} for key in keys]
            self.jobs[job_id] = {"id": job_id, "created_at": datetime.now(timezone.utc).isoformat(), "items": items}
            self.active_keys.update(keys)
            # 提交与关闭受同一把锁保护。先登记整批，防止快速工作线程重复接受。
            for index, key in enumerate(keys):
                self.pool.submit(self._run, job_id, index, calls[key])
            return job_id

    def _run(self, job_id, index, call):
        with self.lock:
            self.jobs[job_id]["items"][index]["state"] = "RUNNING"
        try:
            result = self.service.process_call(call)
            update = {"state": "DONE", "outcome": result.overall_status.value}
        except Exception as exc:
            # 不把上游响应、数据库 DSN 或录音签名链接传给浏览器。
            update = {"state": "FAILED", "error": type(exc).__name__}
        with self.lock:
            self.jobs[job_id]["items"][index].update(update)
            self.active_keys.discard(call.source_call_key)

    def rerun_task(self, task_id):
        """重跑指定任务：从数据库读取原始通话信息重建 CallRecord，强制重新评判。

        返回随机 job_id。
        """
        task = self.service._tasks.get_task_by_id(task_id)
        if task is None:
            raise QueueError("任务不存在")
        source_call_key = task["source_call_key"]
        with self.lock:
            if source_call_key in self.active_keys:
                raise QueueError("该通话正在排队或执行中，请等待当前任务完成")
            if self.closed:
                raise QueueError("服务正在关闭，请稍后重试")
        # 从数据库记录重建 CallRecord（仅需评判所需字段）
        call = CallRecord(
            source_call_key=source_call_key,
            order_id=task.get("order_id"),
            scene_id=task.get("scene_id") or "",
            scene_name=task.get("scene_name") or "",
            seat_id=task.get("seat_id"),
            seat_name=task.get("seat_name"),
            recording_url=task.get("recording_url"),
            call_result="接通",
            talk_seconds=max(self.minimum, 1),  # 已评判过说明具备资格
        )
        with self.lock:
            while len(self.jobs) >= 100:
                finished = next((key for key, job in self.jobs.items() if all(i["state"] in ("DONE", "FAILED") for i in job["items"])), None)
                if finished is None:
                    raise QueueError("当前批次过多，请等待执行完成")
                del self.jobs[finished]
            job_id = uuid4().hex
            items = [{"key": source_call_key, "order_id": call.order_id, "scene_name": call.scene_name,
                      "seat_name": call.seat_name, "state": "QUEUED", "outcome": None, "error": None}]
            self.jobs[job_id] = {"id": job_id, "created_at": datetime.now(timezone.utc).isoformat(), "items": items}
            self.active_keys.add(source_call_key)
        self.pool.submit(self._run_rerun, job_id, 0, call)
        return job_id

    def _run_rerun(self, job_id, index, call):
        with self.lock:
            self.jobs[job_id]["items"][index]["state"] = "RUNNING"
        try:
            result = self.service.process_call(call, force_rerun=True)
            update = {"state": "DONE", "outcome": result.overall_status.value}
        except Exception as exc:
            update = {"state": "FAILED", "error": type(exc).__name__}
        with self.lock:
            self.jobs[job_id]["items"][index].update(update)
            self.active_keys.discard(call.source_call_key)

    def list(self):
        with self.lock:
            return deepcopy(list(reversed(self.jobs.values())))

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True)
