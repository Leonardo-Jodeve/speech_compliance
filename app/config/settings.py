"""
营销通话话术合规质检系统 - 配置管理

原则（开发手册 #47）：
- 敏感信息（数据库密码、ASR Token、TokenHub API Key 等）一律通过环境变量注入，禁止硬编码。
- 非敏感配置放 config.yaml。
- 本模块负责加载 config.yaml 并读取环境变量，提供统一的 Settings 对象。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# 项目根目录（speech_compliance/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config.example.yaml"


class _Secret(str):
    """仅用于 repr 脱敏的字符串类型。"""

    def __repr__(self) -> str:  # pragma: no cover - 仅展示用
        return "******"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _resolve(value, env_placeholder: bool = False):
    """支持 config.yaml 中形如 ${ENV_NAME} 的环境变量引用。"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_name = value[2:-1]
        return _env(env_name)
    return value


class Settings:
    """汇总所有配置。通过 load_settings() 构建。"""

    def __init__(self, data: dict):
        self._data = data

        db = data.get("database", {})
        self.db_host = _resolve(db.get("host", "127.0.0.1"))
        self.db_port = int(_resolve(db.get("port", "5432")))
        self.db_name = _resolve(db.get("name", ""))
        self.db_username = _resolve(db.get("username", ""))
        self.db_password = _resolve(db.get("password", ""))
        self.db_schema = _resolve(db.get("schema", "public"))
        self.db_echo = bool(db.get("echo", False))

        qg = data.get("quality_gate", {})
        self.min_talk_seconds = int(qg.get("min_talk_seconds", 15))

        tok = data.get("tokenhub", {})
        self.tokenhub_base_url = _resolve(tok.get("base_url", ""))
        self.tokenhub_api_key = _resolve(tok.get("api_key", ""))
        self.tokenhub_model = _resolve(tok.get("model", "deepseek-v4-flash-0731"))
        self.tokenhub_temperature = float(tok.get("temperature", 0.1))
        self.tokenhub_timeout_seconds = float(tok.get("timeout_seconds", 120))
        self.tokenhub_max_retries = int(tok.get("max_retries", 2))

        asr_cfg = data.get("asr", {})
        self.asr_upload_url = _resolve(asr_cfg.get("upload_url", ""))
        self.asr_recognize_url = _resolve(asr_cfg.get("recognize_url", ""))
        self.asr_authorization = _resolve(asr_cfg.get("authorization", ""))
        self.asr_staff_token = _resolve(asr_cfg.get("staff_token", ""))
        self.asr_user = _resolve(asr_cfg.get("user", "admin"))
        self.asr_upload_timeout_seconds = float(asr_cfg.get("upload_timeout_seconds", 60))
        self.asr_recognition_timeout_seconds = float(asr_cfg.get("recognition_timeout_seconds", 180))
        self.asr_max_retries = int(asr_cfg.get("max_retries", 2))
        self.asr_query = _resolve(asr_cfg.get(
            "query",
            "请将该音频完整转换为文字。\n"
            "要求：\n"
            "1. 尽可能忠实转写；\n"
            "2. 不总结；\n"
            "3. 不评价；\n"
            "4. 不解释；\n"
            "5. 不补充录音中不存在的内容；\n"
            "6. 只输出转写文本。",
        ))

        rec = data.get("recording", {})
        self.recording_tmp_root = _resolve(rec.get("tmp_root", "/data/speech_qc/tmp"))
        self.recording_download_timeout_seconds = float(rec.get("download_timeout_seconds", 60))
        self.recording_max_retries = int(rec.get("max_retries", 2))

        conf = data.get("concurrency", {})
        self.task_workers = int(conf.get("task_workers", 10))
        self.asr_max_concurrency = int(conf.get("asr_max_concurrency", 5))
        self.llm_max_concurrency = int(conf.get("llm_max_concurrency", 10))

        score = data.get("scoring", {})
        self.pass_score = float(score.get("pass_score", 80.0))

        # 场景无规则时的行为：SKIPPED / REVIEW_REQUIRED
        self.no_rule_behavior = _resolve(score.get("no_rule_behavior", "SKIPPED"))

        m = data.get("model", {})
        self.model_missing_rule_status = _resolve(m.get("missing_rule_status", "REVIEW"))

        log = data.get("logging", {})
        self.log_level = _resolve(log.get("level", "INFO"))
        self.log_format = _resolve(log.get("format", ""))

    @staticmethod
    def _secret(value: str | None) -> str | None:
        if not value:
            return None
        return str(_Secret(value))


def load_config(path: str | Path | None = None) -> Settings:
    """加载配置。优先指定路径，其次项目根 config.yaml。"""
    cfg_path = Path(path) if path else (DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {cfg_path}。请基于 config.example.yaml 创建 config.yaml"
        )
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(data)


_settings: Settings | None = None


def get_settings() -> Settings:
    """全局单例 Settings。"""
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def reload_settings() -> Settings:
    """重新加载配置（测试用）。"""
    global _settings
    _settings = load_config()
    return _settings