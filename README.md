---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'c66f3a1f-385f-4422-9ed3-48a9a410c279'
  PropagateID: 'c66f3a1f-385f-4422-9ed3-48a9a410c279'
  ReservedCode1: 'b830d925-9186-4a83-bdcc-2ddcc2495083'
  ReservedCode2: 'b830d925-9186-4a83-bdcc-2ddcc2495083'
---

# 营销通话话术合规质检系统（一期）

从公司内部呼叫明细表读取符合条件的营销通话记录，下载录音，调用内网 ASR 获得转写文本，
按营销场景加载话术规则，调用 TokenHub LLM 逐项判断合规性，程序校验与评分后写入 PostgreSQL。

## 架构链路

```text
通话记录 → 录音 → ASR → 场景规则 → LLM逐规则判断 → 程序校验与评分 → 结构化入库
```

## 目录结构

```text
speech_compliance/
├── app/
│   ├── config/          # settings.py / logging.py（配置与统一日志）
│   ├── domain/          # CallRecord / Scenario / Rule / Transcript / Compliance
│   ├── adapters/        # asr / tokenhub / recording / call_database
│   ├── repositories/    # rule / task / result
│   ├── services/        # compliance_service / scoring_service / evidence_service / container
│   ├── prompts/         # compliance_prompt.py
│   ├── schemas/         # llm_response.py
│   └── runners/         # single.py / batch.py
├── reference/           # 原三个参考文件（仅参考）
├── migrations/          # 建表 + 种子数据
├── tests/               # Test 1-12
├── config.example.yaml
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入数据库/TokenHub/ASR 信息（敏感项用环境变量）
```

### 3. 建库 + 种子数据

```bash
python migrations/001_create_tables.py
python migrations/002_seed_scenes_rules.py
```

### 4. 运行

单条调试（打印完整链路信息）：

```bash
python -m app.runners.single --start 2026-05-06 --end 2026-05-07 --limit 1
```

批量质检：

```bash
python -m app.runners.batch \
  --start 2026-05-06 --end 2026-05-07 \
  --scene 90131206 --limit 20
```

### 5. 测试

```bash
python -m pytest tests/ -v
```

## 关键设计决策

- 场景为规则第一维度（`act_scene_id` 字符串处理，禁止 float）。
- 场景无规则 → SKIPPED / REVIEW_REQUIRED，绝不默认 100 分。
- LLM 只做逐规则语义判断；分数/状态由 `ScoringService` 纯 Python 计算。
- Evidence 防幻觉：证据片段必须规范化包含匹配于转写文本，否则自动转 REVIEW。
- 幂等：`qc_task.source_call_key` UNIQUE 约束，重复执行不会产生两份有效结果。
- 并发：`ThreadPoolExecutor` + ASR/LLM 全局 Semaphore 限流。
- 日志脱敏：不打印完整号码、Transcript、Token。

## 一期明确不实现

公网录音上传、员工上传、自建 ASR/LLM、GPU、销售分析、话术优化、A/B 实验、前端。

> AI生成