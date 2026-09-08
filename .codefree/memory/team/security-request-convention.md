---
name: security-request-convention
type: project
scope: team
description: "项目后端对非 GET 请求实施了本地工作台安全限制：1. 所有 POST/PUT/DELETE 请求必须携带请求头 X-QC-Request: 1，否则返回 403 Forbidden。2. 如果请求包含 Origin 头，必须与 Host 匹配，防止跨站请求。匹配逻辑需使用规范的 URL 解析（如..."
created: "2026-09-07T07:43:15.286Z"
updated: "2026-09-08T09:14:29.777Z"
---
项目后端对非 GET 请求实施了本地工作台安全限制：1. 所有 POST/PUT/DELETE 请求必须携带请求头 X-QC-Request: 1，否则返回 403 Forbidden。2. 如果请求包含 Origin 头，必须与 Host 匹配，防止跨站请求。匹配逻辑需使用规范的 URL 解析（如 urlparse）比较 netloc，而非字符串直接比较，以兼容浏览器扩展可能移除默认端口（如 8000）导致的 Origin 头差异（例如 Origin: 与 Host: 127.0.0.1:8000 应视为同源）。