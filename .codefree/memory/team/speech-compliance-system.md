---
name: speech-compliance-system
type: project
scope: team
description: 项目是一个基于 AI 的营销通话合规质检系统，自动对营销通话录音进行合规性检查。核心数据流向：1. 源数据库 (sor.dm_eva_feedorder_call_detail) 查询通话记录 2. 资格检查（接通、有录音、时长≥15 秒）3. 幂等检查（基于 source_call_key）4. ...
created: "2026-08-28T02:57:43.572Z"
updated: "2026-09-08T08:43:27.604Z"
---
项目是一个基于 AI 的营销通话合规质检系统，自动对营销通话录音进行合规性检查。核心数据流向：1. 源数据库 (sor.dm_eva_feedorder_call_detail) 查询通话记录 2. 资格检查（接通、有录音、时长≥15 秒）3. 幂等检查（基于 source_call_key）4. 下载录音 → ASR 转写 → 保存转写文本 5. 加载规则（基于场景 ID 和通话时间）6. LLM 质检（TokenHub + deepseek-v4-flash-0731）7. 证据验证（防止 LLM 幻觉）8. 评分计算 → 保存结果 → 更新任务状态。数据库表结构：qc_scene（场景定义）、qc_rule（合规规则）、qc_scene_rule（场景 - 规则关联）、qc_task（任务追踪）、qc_transcript（ASR 转写）、qc_result（总体结果）、qc_rule_result（逐规则结果）。关键机制：幂等控制（UNIQUE(source_call_key) + SHA256）、防幻觉（Evidence 必须存在于转写文本，验证失败自动转 REVIEW）、规则完整性审计（LLM 缺失规则自动补 REVIEW，虚构规则丢弃）、评分逻辑（score = pass_weight / (pass_weight + fail_weight) × 100）、一票否决（CRITICAL + FAIL → overall_status = FAIL）、并发控制（Semaphore 限制 ASR/LLM 并发数）。