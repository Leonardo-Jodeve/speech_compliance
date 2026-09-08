---
name: scoring-config
type: project
scope: team
description: 质检及格分数在 `config.yaml` 的 `scoring.pass_score` 配置项中定义，默认值为 80.0。 修改方法：在 `config.yaml` 中设置 `scoring.pass_score` 为目标分数（如 70.0），修改后需重启服务生效。 代码读取位置：`app/con...
created: "2026-09-07T07:43:15.298Z"
updated: "2026-09-07T07:43:15.298Z"
---
质检及格分数在 `config.yaml` 的 `scoring.pass_score` 配置项中定义，默认值为 80.0。 修改方法：在 `config.yaml` 中设置 `scoring.pass_score` 为目标分数（如 70.0），修改后需重启服务生效。 代码读取位置：`app/config/settings.py` 第 107-108 行。