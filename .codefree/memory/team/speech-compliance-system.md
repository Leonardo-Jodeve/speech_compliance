---
name: speech-compliance-system
type: project
scope: team
description: 项目：营销通话话术合规质检系统（Speech Compliance System） 核心目标：自动对营销通话录音进行合规性检查，判断员工话术是否符合规范要求。 架构分层： - 入口层 (runners)：单条调试 (single.py) 和批量执行 (batch.py) - 服务层 (service...
created: "2026-08-28T02:57:43.572Z"
updated: "2026-08-28T02:57:43.572Z"
---
项目：营销通话话术合规质检系统（Speech Compliance System） 核心目标：自动对营销通话录音进行合规性检查，判断员工话术是否符合规范要求。 架构分层： - 入口层 (runners)：单条调试 (single.py) 和批量执行 (batch.py) - 服务层 (services)：合规质检编排 (compliance_service.py)、评分 (scoring_service.py)、证据验证 (evidence_service.py) - 适配器层 (adapters)：ASR 转写、TokenHub LLM 调用、录音下载、源数据库查询 - 仓储层 (repositories)：规则、任务、结果、转写数据持久化 - 领域层 (domain)：通话记录、合规规则、质检结果、转写文本、营销场景等核心模型 - 配置层 (config)：统一管理 config.yaml 和环境变量 数据库表： - qc_scene：营销场景定义 - qc_rule：合规规则（支持版本管理和生效时间） - qc_scene_rule：场景与规则的多对多关联 - qc_task：质检任务状态追踪（幂等键：source_call_key） - qc_transcript：ASR 转写文本 - qc_result：总体质检结果（得分、状态、统计） - qc_rule_result：逐规则判断结果（含证据和验证状态） 关键机制： - 幂等控制：source_call_key (SHA256) 唯一约束 - 防幻觉：Evidence 必须存在于转写文本，验证失败自动转 REVIEW - 规则审计：LLM 不能发明规则，缺失规则自动补 REVIEW - 并发控制：ASR 和 LLM 调用限制并发数 - 评分逻辑：基于规则权重计算，NOT_APPLICABLE 不计入分母 - 状态流转：PENDING → DOWNLOADING → ASR → LLM → COMPLETED/REVIEW/FAILED/SKIPPED 当前状态：项目已完成初始提交，包含 .gitignore 和完整代码结构，支持单条调试和批量执行。