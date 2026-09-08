---
name: call-scene-data-source
type: project
scope: team
description: 通话记录的营销场景名称（如“其他咨询”）直接读取自源数据库表 `sor.dm_eva_feedorder_call_detail`： - 场景 ID 来自字段 `act_scene_id` - 场景名称来自字段 `act_scene_name` - 读取逻辑在 `app/adapters/call_...
created: "2026-09-07T07:43:15.306Z"
updated: "2026-09-07T07:43:15.306Z"
---
通话记录的营销场景名称（如“其他咨询”）直接读取自源数据库表 `sor.dm_eva_feedorder_call_detail`： - 场景 ID 来自字段 `act_scene_id` - 场景名称来自字段 `act_scene_name` - 读取逻辑在 `app/adapters/call_database_adapter.py` 的 `query_calls` 方法 - 前端显示在 `app/web/static/app.js` 的通话记录列表渲染中 场景配置（如规则关联）存储在 `qc_scene` 表，通过 `source_scene_id` 与源数据关联，但显示名称以源数据库为准。