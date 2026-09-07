"""显式离线演示：临时 SQLite + 虚构通话 + 模拟 ASR/LLM，复用真实编排与评分。"""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from types import SimpleNamespace

from sqlalchemy import create_engine, event, text

from app.config.settings import PROJECT_ROOT
from app.domain.call import CallRecord, build_source_call_key
from app.domain.compliance import ComplianceModelResponse, LlmRuleResult, RuleStatus
from app.domain.transcript import Transcript
from app.repositories.result_repository import ResultRepository, TranscriptRepository
from app.repositories.rule_repository import RuleRepository
from app.repositories.task_repository import TaskRepository
from app.services.compliance_service import ComplianceTaskService
from app.services.scoring_service import ScoringService
from app.web.jobs import JobManager
from app.web.repository import AdminRepository
from app.web.schemas import BindingInput, RuleInput, SceneInput


def create_demo_engine(path):
    engine = create_engine(f"sqlite:///{Path(path).as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA busy_timeout=10000")

    spec = importlib.util.spec_from_file_location("qc_migration", PROJECT_ROOT / "migrations" / "001_create_tables.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    ddl = migration.build_ddl("main").replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
    # SQLite REFERENCES 只接受本 schema 内的无前缀表名。
    ddl = ddl.replace("REFERENCES main.", "REFERENCES ")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        for statement in ddl.split(";"):
            statement = statement.strip()
            if statement and not statement.startswith("CREATE INDEX"):
                conn.execute(text(statement))
    return engine


class DemoRecording:
    def __init__(self, root):
        self.root = Path(root)

    def download(self, url, task_id, ext="wav"):
        sleep(.2)
        path = self.root / f"{task_id}.txt"
        path.write_text(url, encoding="utf-8")
        return path

    def cleanup(self, task_id):
        (self.root / f"{task_id}.txt").unlink(missing_ok=True)


class DemoAsr:
    def transcribe(self, path, task_id=0):
        sleep(.3)
        marker = Path(path).read_text(encoding="utf-8")
        if marker.endswith("failure"):
            raise RuntimeError("模拟录音服务不可用，用于演示单通失败隔离")
        transcript = "坐席：您好，这里是客户服务中心。请问方便介绍一下套餐吗？\n客户：可以。\n"
        if marker.endswith("pass"):
            transcript += "坐席：套餐每月费用为 99 元，合约期为 12 个月，到期恢复原价。\n客户：好的，我了解了。"
        else:
            transcript += "坐席：这个套餐很适合您，我帮您办理吧。\n客户：我再考虑一下。"
        return Transcript(text=transcript, asr_file_id=f"demo-{task_id}", raw_answer=transcript)


class DemoLlm:
    def evaluate_rules(self, transcript, scenario, rules):
        sleep(.3)
        phrases = {"DISCLOSE_PRICE": "每月费用为 99 元", "DISCLOSE_CONTRACT": "合约期为 12 个月"}
        results = []
        for rule in rules:
            phrase = phrases.get(rule.rule_code)
            status = RuleStatus.REVIEW if not phrase else RuleStatus.PASS if phrase in transcript.text else RuleStatus.FAIL
            results.append(LlmRuleResult(rule_code=rule.rule_code, status=status, confidence=.95,
                reason="演示数据：明确披露对应信息。" if status == RuleStatus.PASS else "演示数据：未找到对应披露信息，请查看原文。",
                evidence=[phrase] if status == RuleStatus.PASS else ["这个套餐很适合您"] if status == RuleStatus.FAIL else []))
        return ComplianceModelResponse(rule_results=results)


class DemoCalls:
    def __init__(self):
        self.records = []
        today = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
        for i in range(12):
            start = today - timedelta(days=i // 4, minutes=i * 13)
            order_id = f"17773477344795300000000000000000000000{i:02d}"
            marker = "failure" if i == 2 else "fail" if i % 3 == 1 else "pass"
            self.records.append(CallRecord(source_call_key=build_source_call_key(order_id,start,"13900000000","13800000000"),
                order_id=order_id, scene_id="DEMO_001", scene_name="家庭融合套餐（演示）", seat_id=f"DEMO_{i%3+1:03d}",
                seat_name=["演示坐席 A","演示坐席 B","演示坐席 C"][i%3], start_time=start, talk_seconds=8 if i == 11 else 62+i*17,
                call_result="接通", recording_url=f"demo://{marker}", guest_called_nbr="13800000000"))

    def query_calls(self, start_time=None,end_time=None,scene_ids=None,seat_ids=None,limit=None,only_qualifiable=True,offset=0):
        records = [c for c in self.records if (not start_time or c.start_time >= start_time)
                   and (not end_time or c.start_time < end_time) and (not scene_ids or c.scene_id in scene_ids)
                   and (not seat_ids or c.seat_id in seat_ids) and (not only_qualifiable or c.is_qualifiable())]
        return records[offset:offset+limit if limit else None]


class DemoRuntime:
    def __init__(self):
        self.temp = TemporaryDirectory(prefix="speech-qc-demo-")
        self.repo = AdminRepository(create_demo_engine(Path(self.temp.name) / "demo.sqlite"), "main")
        self.settings = SimpleNamespace(min_talk_seconds=15, pass_score=80, task_workers=2, tokenhub_model="离线模拟（非真实模型）")
        scene = self.repo.save("scenes", SceneInput(source_scene_id="DEMO_001",scene_name="家庭融合套餐（演示）",description="离线虚构示例，仅供体验操作流程。").model_dump())
        for code,name,weight in (("DISCLOSE_PRICE","明确告知套餐费用",60),("DISCLOSE_CONTRACT","告知合约期限",40)):
            rule = self.repo.save("rules", RuleInput(rule_code=code,rule_name=name,weight=weight,severity="HIGH",
                description="确认坐席向客户明确披露相关资费或期限信息。",judge_instruction="依据原文提供判断和证据；未明确披露则不通过。").model_dump())
            self.repo.save("bindings", BindingInput(scene_id=scene["id"],rule_id=rule["id"]).model_dump())
        engine = self.repo.engine
        self.service = ComplianceTaskService(engine,TaskRepository(engine,"main"),TranscriptRepository(engine,"main"),
            ResultRepository(engine,"main"),RuleRepository(engine,"main"),DemoAsr(),DemoLlm(),DemoRecording(self.temp.name),ScoringService(),schema="main")
        self.calls = DemoCalls()
        self.jobs = JobManager(self.service,2)
        self.demo = True

    def initialize(self):
        return self

    def close(self):
        self.jobs.close()
        self.repo.engine.dispose()
        self.temp.cleanup()
