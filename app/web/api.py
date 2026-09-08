"""FastAPI 同源本地工作台；所有网络处理仍由既有 Service 完成。"""
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.adapters.call_database_adapter import CallDatabaseAdapter
from app.config.settings import load_config
from app.services.container import build_services
from app.web.jobs import JobManager, QueueError
from app.web.repository import AdminRepository, ConflictError
from app.web.schemas import MODELS, RunInput

STATIC = Path(__file__).parent / "static"


class Runtime:
    def __init__(self):
        self.lock = Lock()
        self.ready = False

    def initialize(self):
        with self.lock:
            if self.ready:
                return self
            settings = load_config()
            deps = build_services(settings)
            self.settings = settings
            self.deps = deps
            self.repo = AdminRepository(deps["engine"], settings.db_schema or "public")
            self.calls = CallDatabaseAdapter(engine=deps["engine"], min_talk_seconds=settings.min_talk_seconds)
            self.jobs = JobManager(deps["compliance_service"], settings.task_workers, settings.min_talk_seconds)
            self.ready = True
        return self

    def close(self):
        if self.ready:
            self.jobs.close()
            for name in ("asr_adapter", "recording_adapter"):
                self.deps[name]._client.close()
            self.deps["engine"].dispose()


def create_app(runtime=None):
    runtime = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(app):
        yield
        runtime.close()

    app = FastAPI(title="外呼话术评判平台", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        # 本地单用户工具：拒绝网页跨站提交和 DNS rebinding。
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "仅允许从本地工作台提交操作"}, status_code=403)
            if request.headers.get("x-qc-request") != "1":
                return JSONResponse({"detail": "缺少工作台请求标记"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        if isinstance(exc, IntegrityError):
            return JSONResponse({"detail": "编号或场景规则关联已存在，或关联记录已被删除，请检查后重试"}, status_code=409)
        return JSONResponse({"detail": "数据库不可用或表结构不完整。请检查内网/VPN、config.yaml 和迁移 001；连接恢复后刷新即可。"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def request_error(request, exc):
        return JSONResponse({"detail": "请求参数不合法，请检查日期、必填项和数值范围"}, status_code=422)

    def rt():
        try:
            return runtime.initialize()
        except (TypeError, ValueError, OSError):
            raise HTTPException(503, "配置尚未就绪，请检查 config.yaml 中的数据库、ASR 和 TokenHub 配置") from None

    def resource_model(resource):
        if resource not in MODELS:
            raise HTTPException(404, "参数表不存在")
        return MODELS[resource]

    def save(resource, data, row_id=None):
        model = resource_model(resource)
        try:
            parsed = model.model_validate(data).model_dump()
        except ValidationError as exc:
            # 只返回字段路径和错误，不回显输入内容。
            detail = "；".join(f"{'.'.join(map(str, e['loc'])) or '表单'}: {e['msg']}" for e in exc.errors())
            raise HTTPException(422, detail) from None
        try:
            result = rt().repo.save(resource, parsed, row_id)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        if result is None:
            raise HTTPException(404, "记录已不存在")
        return result

    @app.get("/api/health")
    def health():
        state = rt()
        with state.repo.engine.connect() as conn:
            for name in ("qc_scene", "qc_rule", "qc_scene_rule", "qc_task", "qc_result", "qc_rule_result", "qc_transcript"):
                conn.execute(text(f"SELECT 1 FROM {state.repo.table(name)} LIMIT 1"))
        return {"database": "connected", "demo": getattr(state, "demo", False), "min_talk_seconds": state.settings.min_talk_seconds,
                "pass_score": state.settings.pass_score, "workers": min(state.settings.task_workers, 20),
                "model": state.settings.tokenhub_model}

    @app.get("/api/admin/{resource}")
    def list_rows(resource: str, q: str = Query("", max_length=200), page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100)):
        resource_model(resource)
        return rt().repo.list(resource, q, page, size)

    @app.get("/api/admin/{resource}/{row_id}")
    def get_row(resource: str, row_id: int):
        resource_model(resource)
        row = rt().repo.get(resource, row_id)
        if row is None:
            raise HTTPException(404, "记录已不存在")
        return row

    @app.post("/api/admin/{resource}", status_code=201)
    def create_row(resource: str, data: dict = Body(...)):
        return save(resource, data)

    @app.put("/api/admin/{resource}/{row_id}")
    def update_row(resource: str, row_id: int, data: dict = Body(...)):
        return save(resource, data, row_id)

    @app.delete("/api/admin/{resource}/{row_id}")
    def delete_row(resource: str, row_id: int):
        resource_model(resource)
        try:
            deleted = rt().repo.delete(resource, row_id)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        if not deleted:
            raise HTTPException(404, "记录已不存在")
        return {"deleted": True}

    @app.get("/api/admin/scenes/{scene_id}/bindings")
    def list_scene_bindings(scene_id: int):
        """查询指定场景下的全部规则关联（不启用分页，适合场景维度配置页）。"""
        try:
            return rt().repo.list_bindings_for_scene(scene_id)
        except ConflictError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/api/calls")
    def query_calls(start: date, end: date, scene: str = Query("", max_length=64), seat: str = Query("", max_length=64),
                    page: int = Query(1, ge=1, le=10000), size: int = Query(30, ge=1, le=100), only_qualifiable: bool = True):
        if end < start or (end - start).days > 31:
            raise HTTPException(422, "结束日期不能早于开始日期，单次查询最多 32 个自然日")
        state = rt()
        calls = state.calls.query_calls(start_time=datetime.combine(start, time.min), end_time=datetime.combine(end + timedelta(days=1), time.min),
                                        scene_ids=[scene] if scene else None, seat_ids=[seat] if seat else None,
                                        limit=size + 1, offset=(page - 1) * size, only_qualifiable=only_qualifiable)
        has_more = len(calls) > size
        calls = calls[:size]
        states = state.repo.task_states([c.source_call_key for c in calls])
        search_id = state.jobs.cache_search(calls)
        return {"search_id": search_id, "page": page, "has_more": has_more, "items": [
            {"key": c.source_call_key, "order_id": c.order_id, "scene_id": c.scene_id, "scene_name": c.scene_name,
             "seat_id": c.seat_id, "seat_name": c.seat_name, "phone": c.masked_phone(), "start_time": c.start_time,
             "talk_seconds": c.talk_seconds, "call_result": c.call_result, "has_recording": bool(c.recording_url),
             "qualifiable": c.is_qualifiable(state.settings.min_talk_seconds), "task": states.get(c.source_call_key)} for c in calls]}

    @app.post("/api/jobs", status_code=202)
    def submit_job(data: RunInput):
        try:
            return {"id": rt().jobs.submit(data.search_id, data.call_keys)}
        except QueueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/jobs")
    def list_jobs():
        state = rt()
        jobs = state.jobs.list()
        states = state.repo.task_states({i["key"] for j in jobs for i in j["items"]})
        for job in jobs:
            for item in job["items"]:
                item["task"] = states.get(item["key"])
        return {"items": jobs}

    @app.get("/api/tasks")
    def tasks(page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100), status: str | None = Query(None, max_length=32)):
        return rt().repo.tasks(page, size, status)

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: int):
        detail = rt().repo.task_detail(task_id)
        if detail is None:
            raise HTTPException(404, "任务不存在")
        return detail

    @app.post("/api/tasks/{task_id}/rerun", status_code=202)
    def rerun_task(task_id: int):
        state = rt()
        # 确认任务存在
        detail = state.repo.task_detail(task_id)
        if detail is None:
            raise HTTPException(404, "任务不存在")
        task = detail["task"]
        if task["status"] not in ("COMPLETED", "REVIEW_REQUIRED", "SKIPPED", "FAILED"):
            raise HTTPException(409, "任务正在执行中，无法重跑")
        try:
            return {"id": state.jobs.rerun_task(task_id)}
        except QueueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
