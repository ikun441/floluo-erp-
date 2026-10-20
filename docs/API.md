# API 规范

/api/v1 前缀；FastAPI /openapi.json 为已实现接口的准确契约。未实现模块不注册伪接口。
认证使用 HttpOnly 会话 Cookie；GET /auth/me 返回当前用户；修改请求要求 X-CSRF-Token 与 csrf Cookie 配对并匹配会话摘要。登录接口校验 Origin（如提供）。凭据不放 localStorage。

错误：401 未认证/失效，403 权限/字段/CSRF，404 不存在或不可见记录（避免 ID 探测），409 版本/完整性冲突，422 schema 错误。响应含 X-Trace-ID，错误不返回内部异常或 SQL。

写入通过同一授权事务。策略发布采用 expected_revision 乐观版本；业务 PATCH 包含 version，旧版本返回 409。分页 limit 最大 100，固定 UUID id 排序。后续导出任务绑定用户与策略版本，执行与下载均重新授权。
