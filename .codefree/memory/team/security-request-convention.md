---
name: security-request-convention
type: project
scope: team
description: "项目后端对非 GET 请求实施了本地工作台安全限制： 1. 所有 POST/PUT/DELETE 请求必须携带请求头 `X-QC-Request: 1`，否则返回 403 Forbidden。 2. 如果请求包含 Origin 头，必须与 Host 匹配，防止跨站请求。 3. 前端 `app/web..."
created: "2026-09-07T07:43:15.286Z"
updated: "2026-09-07T07:43:15.286Z"
---
项目后端对非 GET 请求实施了本地工作台安全限制： 1. 所有 POST/PUT/DELETE 请求必须携带请求头 `X-QC-Request: 1`，否则返回 403 Forbidden。 2. 如果请求包含 Origin 头，必须与 Host 匹配，防止跨站请求。 3. 前端 `app/web/static/app.js` 的 `api` 函数已默认添加该请求头。 4. 若出现 403 错误，需检查浏览器扩展是否拦截请求头、前端文件是否被修改或存在缓存问题。