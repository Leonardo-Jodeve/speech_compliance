"""离线接口集成测试：真实参数表、编排、评分、结果入库，仅模拟外部服务。"""
from datetime import timedelta
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.web.api import create_app
from app.web.demo import DemoRuntime
from app.web.jobs import QueueError


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr("app.web.demo.sleep", lambda _: None)
    rt = DemoRuntime()
    yield rt
    rt.close()


@pytest.fixture
def client(runtime):
    # runtime 由 fixture 统一清理，不重复进入 lifespan。
    with TestClient(create_app(runtime), headers={"X-QC-Request": "1"}) as c:
        yield c


def search(client, runtime, **params):
    day = runtime.calls.records[0].start_time.date().isoformat()
    response = client.get("/api/calls", params={"start": day, "end": day, **params})
    assert response.status_code == 200
    return response.json()


def await_jobs(runtime):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        jobs = runtime.jobs.list()
        if all(i["state"] in ("DONE", "FAILED") for j in jobs for i in j["items"]):
            return jobs
        sleep(.01)
    pytest.fail("后台队列没有在预期时间内结束")


def test_admin_crud_relations_precision_and_conflicts(client):
    long_id = "17773477344795300000000000000000000001234"
    scene = {"source_scene_id": long_id, "scene_name": "测试场景"}
    response = client.post("/api/admin/scenes", json=scene)
    assert response.status_code == 201
    scene_id = response.json()["id"]
    assert response.json()["source_scene_id"] == long_id
    assert client.post("/api/admin/scenes", json=scene).status_code == 409
    rule = client.post("/api/admin/rules", json={"rule_code": "R_NEW", "rule_name": "费用披露"}).json()
    assert len(rule["content_hash"]) == 64 and rule["revision_id"]
    binding = client.post("/api/admin/bindings", json={"scene_id":scene_id,"rule_id":rule["id"],"weight_override":0})
    assert binding.status_code == 201 and binding.json()["weight_override"] == 0
    assert client.delete(f"/api/admin/scenes/{scene_id}").status_code == 409
    assert client.delete(f"/api/admin/rules/{rule['id']}").status_code == 409
    update = client.put(f"/api/admin/scenes/{scene_id}", json={**scene,"scene_name":"更新名称","enabled":False})
    assert update.status_code == 200 and not update.json()["enabled"]
    assert client.get("/api/admin/scenes",params={"q":long_id}).json()["total"] == 1
    assert client.delete(f"/api/admin/bindings/{binding.json()['id']}").status_code == 200
    assert client.delete(f"/api/admin/rules/{rule['id']}").status_code == 200
    assert client.delete(f"/api/admin/scenes/{scene_id}").status_code == 200
    assert client.get(f"/api/admin/scenes/{scene_id}").status_code == 404


@pytest.mark.parametrize("body", [
    {"rule_code":"x","rule_name":" ","weight":1},
    {"rule_code":"x","rule_name":"规则","weight":-1},
    {"rule_code":"x","rule_name":"规则","weight":1000},
    {"rule_code":"x","rule_name":"规则","rule_type":"UNSUPPORTED"},
    {"rule_code":"x","rule_name":"规则","effective_from":"2026-09-07T12:00","effective_to":"2026-09-07T11:00"},
    {"rule_code":"x","rule_name":"规则","untrusted_sql":"DROP TABLE qc_rule"},
])
def test_rule_validation(client, body):
    assert client.post("/api/admin/rules",json=body).status_code == 422


def test_update_rule_hash_and_binding(client):
    rule = client.get("/api/admin/rules/1").json()
    response = client.put("/api/admin/rules/1",json={"rule_code":rule["rule_code"],"rule_name":"新规则名称","weight":20})
    assert response.status_code == 200
    assert response.json()["content_hash"] != rule["content_hash"]
    assert response.json()["revision_id"] != rule["revision_id"]
    response = client.put("/api/admin/bindings/1",json={"scene_id":1,"rule_id":1,"enabled":False,"weight_override":25})
    assert response.status_code == 200 and not response.json()["enabled"]
    assert client.post("/api/admin/bindings",json={"scene_id":99999,"rule_id":1}).status_code == 409
    assert client.post("/api/admin/scenes",json={"source_scene_id":123,"scene_name":"场景"}).status_code == 422


def test_origin_guard_and_table_whitelist(client):
    body = {"source_scene_id":"x","scene_name":"x"}
    assert client.post("/api/admin/scenes",json=body,headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/admin/scenes",json=body,headers={"X-QC-Request":""}).status_code == 403
    assert client.get("/api/admin/qc_task").status_code == 404
    assert client.get("/",headers={"Host":"evil.example"}).status_code == 400


def test_call_selection_is_server_owned_and_paginated(client,runtime):
    first = search(client,runtime,size=2)
    second = search(client,runtime,size=2,page=2)
    assert first["has_more"] and first["items"][0]["key"] != second["items"][0]["key"]
    row = first["items"][0]
    assert isinstance(row["order_id"],str) and len(row["order_id"]) > 30
    assert "recording_url" not in row and "13800000000" not in row["phone"]
    invalid = {"search_id": first["search_id"], "call_keys": [second["items"][0]["key"]]}
    assert client.post("/api/jobs",json=invalid).status_code == 409
    assert client.post("/api/jobs",json={**invalid,"recording_url":"https://evil.example"}).status_code == 422
    assert client.get("/api/calls",params={"start":"2026-09-07","end":"2026-09-06"}).status_code == 422


def test_selected_batch_runs_pipeline_isolates_failure_and_persists_reports(client,runtime):
    found = search(client,runtime)
    keys = [row["key"] for row in found["items"][:3]]  # PASS / FAIL / 上游异常
    response = client.post("/api/jobs",json={"search_id":found["search_id"],"call_keys":keys})
    assert response.status_code == 202
    jobs = await_jobs(runtime)
    assert [i["state"] for i in jobs[0]["items"]] == ["DONE","DONE","FAILED"]
    history = client.get("/api/tasks").json()
    assert history["total"] == 3
    by_key = {i["source_call_key"]:i for i in history["items"]}
    assert by_key[keys[0]]["overall_status"] == "PASS"
    assert by_key[keys[1]]["overall_status"] == "FAIL"
    detail = client.get(f"/api/tasks/{by_key[keys[0]]['id']}").json()
    assert "99 元" in detail["transcript"] and len(detail["rules"]) == 2
    assert detail["result"]["score"] == 100
    assert "recording_url" not in detail["task"] and "error_message" not in detail["task"]
    assert client.get("/api/tasks",params={"status":"FAILED"}).json()["total"] == 1
    assert client.get("/api/jobs").json()["items"][0]["items"][0]["task"]["id"]


def test_queue_rejects_duplicates_and_expired_snapshots(runtime):
    started, release = Event(), Event()
    original = runtime.jobs.service.process_call
    def blocking(call):
        started.set()
        assert release.wait(5)
        return original(call)
    runtime.jobs.service.process_call = blocking
    call = runtime.calls.records[0]
    snapshot = runtime.jobs.cache_search([call])
    try:
        runtime.jobs.submit(snapshot,[call.source_call_key,call.source_call_key])
        assert started.wait(2)
        with pytest.raises(QueueError,match="正在排队"):
            runtime.jobs.submit(snapshot,[call.source_call_key])
        assert len(runtime.jobs.list()[0]["items"]) == 1
    finally:
        release.set()
    await_jobs(runtime)
    runtime.jobs.searches[snapshot] = (0,{call.source_call_key:call})
    with pytest.raises(QueueError,match="已过期"):
        runtime.jobs.submit(snapshot,[call.source_call_key])


def test_failed_after_asr_can_retry_without_duplicate_transcript_or_results(runtime,monkeypatch):
    call = runtime.calls.records[0]
    llm = runtime.service._llm
    original = llm.evaluate_rules
    def fail(*args):
        raise RuntimeError("synthetic upstream failure")
    monkeypatch.setattr(llm,"evaluate_rules",fail)
    with pytest.raises(RuntimeError): runtime.service.process_call(call)
    task = runtime.repo.task_states([call.source_call_key])[call.source_call_key]
    assert task["status"] == "FAILED" and runtime.repo.task_detail(task["id"])["transcript"]
    monkeypatch.setattr(llm,"evaluate_rules",original)
    assert runtime.service.process_call(call).overall_status.value == "PASS"
    repeated = runtime.service.process_call(call)
    assert repeated.overall_status.value == "SKIPPED"
    with runtime.repo.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM qc_transcript")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM qc_result")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM qc_rule_result")).scalar_one() == 2
        task = conn.execute(text("SELECT * FROM qc_task")).mappings().one()
        assert task["retry_count"] == 1 and task["error_code"] is None


def test_disabled_binding_and_no_rules_never_default_to_pass(runtime):
    with runtime.repo.engine.begin() as conn:
        conn.execute(text("UPDATE qc_scene_rule SET enabled=FALSE"))
    result = runtime.service.process_call(runtime.calls.records[0])
    assert result.overall_status.value == "SKIPPED" and result.score == -1
    assert runtime.repo.tasks()["items"][0]["error_code"] == "SCENE_RULE_NOT_CONFIGURED"


def test_result_and_evidence_save_roll_back_together(runtime):
    from sqlalchemy.exc import IntegrityError
    result = runtime.service.process_call(runtime.calls.records[0])
    result.score = 12
    result.rule_results[0].rule_code = None  # 触发逐规则保存失败
    with pytest.raises(IntegrityError):
        runtime.service._results.save_with_rules(result,1)
    detail = runtime.repo.task_detail(1)
    assert detail["result"]["score"] == 100 and len(detail["rules"]) == 2


def test_postgres_lock_blocks_duplicate_and_releases_after_exception(runtime,monkeypatch):
    from unittest.mock import MagicMock
    connection = MagicMock()
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value.__enter__.return_value = connection
    runtime.service._engine = engine
    call = runtime.calls.records[0]
    process = MagicMock(side_effect=RuntimeError("test failure"))
    monkeypatch.setattr(runtime.service,"_process_call",process)
    connection.execute.return_value.scalar.return_value = False
    assert runtime.service.process_call(call).error_code == "TASK_ALREADY_RUNNING"
    process.assert_not_called()
    connection.execute.return_value.scalar.return_value = True
    with pytest.raises(RuntimeError): runtime.service.process_call(call)
    assert "pg_advisory_unlock" in str(connection.execute.call_args[0][0])
    assert connection.commit.call_count == 3


def test_ui_and_database_unavailable_error_are_safe(client,monkeypatch,runtime):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json()["demo"] is True
    from sqlalchemy.exc import OperationalError
    def fail(*args,**kwargs):
        raise OperationalError("SQL with sensitive data",{},Exception("password=secret"))
    monkeypatch.setattr(runtime.repo,"list",fail)
    response = client.get("/api/admin/scenes")
    assert response.status_code == 503
    assert "secret" not in response.text and "SQL with" not in response.text
