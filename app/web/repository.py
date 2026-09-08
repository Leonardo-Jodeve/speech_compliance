"""参数表 CRUD 与只读任务查询。SQL 标识符仅来自白名单。"""
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from app.domain.rule import ComplianceRule, RuleType, Severity
from app.repositories.rule_repository import content_hash_of

TABLES = {"scenes": "qc_scene", "rules": "qc_rule", "bindings": "qc_scene_rule"}


class ConflictError(ValueError):
    pass


class AdminRepository:
    def __init__(self, engine, schema="public"):
        if schema and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("数据库 schema 必须是合法标识符")
        self.engine = engine
        self.schema = schema

    def table(self, name):
        return f'"{self.schema}".{name}' if self.schema else name

    def row(self, value):
        result = dict(value)
        if self.engine.dialect.name == "sqlite":
            # 演示库 CURRENT_TIMESTAMP 返回无时区的 UTC 字符串。
            for key in ("created_at", "updated_at", "started_at", "finished_at"):
                if isinstance(result.get(key), str):
                    result[key] = datetime.fromisoformat(result[key]).replace(tzinfo=timezone.utc)
        return result

    def list(self, resource, q="", page=1, size=30):
        table = self.table(TABLES[resource])
        if resource == "bindings":
            source = (f"{table} t JOIN {self.table('qc_scene')} s ON s.id=t.scene_id "
                      f"JOIN {self.table('qc_rule')} r ON r.id=t.rule_id")
            columns = "t.*, s.source_scene_id, s.scene_name, r.rule_code, r.rule_name, r.weight AS default_weight"
            search = "s.scene_name || ' ' || s.source_scene_id || ' ' || r.rule_code || ' ' || r.rule_name"
        else:
            source, columns = f"{table} t", "t.*"
            search = "t.scene_name || ' ' || t.source_scene_id" if resource == "scenes" else "t.rule_name || ' ' || t.rule_code"
        where = f"LOWER({search}) LIKE :q"
        params = {"q": f"%{q.lower()}%", "size": size, "offset": (page - 1) * size}
        with self.engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM {source} WHERE {where}"), params).scalar_one()
            rows = conn.execute(text(f"SELECT {columns} FROM {source} WHERE {where} ORDER BY t.id DESC LIMIT :size OFFSET :offset"), params).mappings().all()
        return {"items": [self.row(r) for r in rows], "total": total, "page": page, "size": size}

    def get(self, resource, row_id):
        with self.engine.connect() as conn:
            row = conn.execute(text(f"SELECT * FROM {self.table(TABLES[resource])} WHERE id=:id"), {"id": row_id}).mappings().first()
        return self.row(row) if row else None

    def save(self, resource, data, row_id=None):
        data = dict(data)
        if resource == "rules":
            rule = ComplianceRule(**{**data, "rule_type": RuleType(data["rule_type"]), "severity": Severity(data["severity"])})
            data.update(content_hash=content_hash_of(rule), revision_id=uuid4().hex)
        table = self.table(TABLES[resource])
        with self.engine.begin() as conn:
            if resource == "bindings":
                for column, target in (("scene_id", "qc_scene"), ("rule_id", "qc_rule")):
                    if not conn.execute(text(f"SELECT id FROM {self.table(target)} WHERE id=:id"), {"id": data[column]}).first():
                        raise ConflictError("关联的场景或规则不存在，请刷新后重试")
            if row_id is None:
                columns = ", ".join(data)
                values = ", ".join(f":{key}" for key in data)
                sql = f"INSERT INTO {table} ({columns}) VALUES ({values}) RETURNING *"
            else:
                sets = ", ".join(f"{key}=:{key}" for key in data)
                if resource != "bindings":
                    sets += ", updated_at=CURRENT_TIMESTAMP"
                sql = f"UPDATE {table} SET {sets} WHERE id=:id RETURNING *"
                data["id"] = row_id
            row = conn.execute(text(sql), data).mappings().first()
        return self.row(row) if row else None

    def delete(self, resource, row_id):
        with self.engine.begin() as conn:
            if resource != "bindings":
                column = "scene_id" if resource == "scenes" else "rule_id"
                count = conn.execute(text(f"SELECT COUNT(*) FROM {self.table('qc_scene_rule')} WHERE {column}=:id"), {"id": row_id}).scalar_one()
                if count:
                    raise ConflictError(f"仍有 {count} 条场景规则关联，请先删除关联，或将本条设为停用")
            row = conn.execute(text(f"DELETE FROM {self.table(TABLES[resource])} WHERE id=:id RETURNING id"), {"id": row_id}).first()
        return row is not None

    def tasks(self, page=1, size=30, status=None):
        params = {"offset": (page - 1) * size, "size": size, "status": status}
        where = "t.status=:status" if status else "TRUE"
        with self.engine.connect() as conn:
            total = conn.execute(text(f"SELECT COUNT(*) FROM {self.table('qc_task')} t WHERE {where}"), params).scalar_one()
            rows = conn.execute(text(
                f"SELECT t.id, t.source_call_key, t.order_id, t.scene_name, t.scene_id, t.seat_name, t.seat_id, "
                f"t.status, t.current_stage, t.error_code, t.created_at, t.finished_at, r.score, r.overall_status "
                f"FROM {self.table('qc_task')} t LEFT JOIN {self.table('qc_result')} r ON r.task_id=t.id "
                f"WHERE {where} ORDER BY t.id DESC LIMIT :size OFFSET :offset"
            ), params).mappings().all()
        return {"items": [self.row(r) for r in rows], "total": total, "page": page, "size": size}

    def task_detail(self, task_id):
        with self.engine.connect() as conn:
            task = conn.execute(text(f"SELECT id, source_call_key, order_id, scene_name, seat_name, status, current_stage, error_code, created_at, started_at, finished_at FROM {self.table('qc_task')} WHERE id=:id"), {"id": task_id}).mappings().first()
            if task is None:
                return None
            transcript = conn.execute(text(f"SELECT transcript_text FROM {self.table('qc_transcript')} WHERE task_id=:id"), {"id": task_id}).scalar()
            result = conn.execute(text(f"SELECT * FROM {self.table('qc_result')} WHERE task_id=:id"), {"id": task_id}).mappings().first()
            rules = []
            if result:
                rules = conn.execute(text(f"SELECT * FROM {self.table('qc_rule_result')} WHERE result_id=:id ORDER BY id"), {"id": result["id"]}).mappings().all()
        return {"task": self.row(task), "transcript": transcript, "result": self.row(result) if result else None, "rules": [self.row(r) for r in rules]}

    def task_states(self, keys):
        if not keys:
            return {}
        from sqlalchemy import bindparam
        stmt = text(f"SELECT source_call_key, id, status, current_stage, error_code FROM {self.table('qc_task')} WHERE source_call_key IN :keys").bindparams(bindparam("keys", expanding=True))
        with self.engine.connect() as conn:
            return {r["source_call_key"]: dict(r) for r in conn.execute(stmt, {"keys": list(keys)}).mappings()}

    def list_bindings_for_scene(self, scene_id):
        """查询指定场景下的全部规则关联（不分页）。"""
        table = self.table(TABLES["bindings"])
        source = (f"{table} t JOIN {self.table('qc_scene')} s ON s.id=t.scene_id "
                  f"JOIN {self.table('qc_rule')} r ON r.id=t.rule_id")
        columns = ("t.*, s.source_scene_id, s.scene_name, "
                   "r.rule_code, r.rule_name, r.rule_type, r.severity, "
                   "r.weight AS default_weight, r.enabled AS rule_enabled")
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT {columns} FROM {source} WHERE t.scene_id=:sid ORDER BY r.rule_code"
            ), {"sid": scene_id}).mappings().all()
        return {"items": [self.row(r) for r in rows]}
