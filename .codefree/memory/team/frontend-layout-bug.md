---
name: frontend-layout-bug
type: project
scope: team
description: 前端管理界面存在布局切换 BUG：当用户点击“场景规则关联”进入分栏视图后，再切换回“营销场景”或“话术规则”时，右侧区域无法恢复为标准单栏布局，导致页面卡死。根本原因：loadAdmin() 函数在恢复标准布局时，仅检查 #add-record 元素是否存在，未检测并清除分栏布局特有的 .bind...
created: "2026-09-08T08:45:56.397Z"
updated: "2026-09-08T09:14:23.565Z"
---
前端管理界面存在布局切换 BUG：当用户点击“场景规则关联”进入分栏视图后，再切换回“营销场景”或“话术规则”时，右侧区域无法恢复为标准单栏布局，导致页面卡死。根本原因：loadAdmin() 函数在恢复标准布局时，仅检查 #add-record 元素是否存在，未检测并清除分栏布局特有的 .bindings-layout 元素，且 navigate() 函数在布局恢复前尝试访问 #admin-title 导致空指针错误。修复方案：在 navigate() 函数中增加对 .bindings-layout 的检测，强制清除分栏布局并重新渲染标准视图，确保在设置文本内容前 DOM 元素已存在。