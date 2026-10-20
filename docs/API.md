# API 规范

/api/v1 前缀；FastAPI /openapi.json 为已实现接口的准确契约。未实现模块不注册伪接口。
认证使用 HttpOnly 会话 Cookie；GET /auth/me 返回当前用户；修改请求要求 X-CSRF-Token 与 csrf Cookie 配对并匹配会话摘要。登录接口校验 Origin（如提供）。凭据不放 localStorage。

错误：401 未认证/失效，403 权限/字段/CSRF，404 不存在或不可见记录（避免 ID 探测），409 版本/完整性冲突，422 schema 错误。响应含 X-Trace-ID，错误不返回内部异常或 SQL。

写入通过同一授权事务。策略发布采用 expected_revision 乐观版本；业务 PATCH 包含 version，旧版本返回 409。分页 limit 最大 100，固定 UUID id 排序。后续导出任务绑定用户与策略版本，执行与下载均重新授权。

## 已实现的采购资料接口

认证后GET `/api/v1/resource_catalog`返回资源注册表中的字段、动作和可用范围，仅含契约元数据，无业务记录。权限界面以此配置矩阵。

`categories`、`suppliers`、`warehouses`与`products`使用以下统一接口：

| 方法 | 路径 | 请求 |
| --- | --- | --- |
| GET | /api/v1/{resource}?limit=50&after=UUID | 范围过滤后固定ID分页 |
| GET | /api/v1/{resource}/{id} | 不可见与不存在统一404 |
| POST | /api/v1/{resource} | `{ "data": { ... } }` |
| PATCH | /api/v1/{resource}/{id} | `{ "version": 1, "data": { ... } }` |

分类字段name、parent_id；商品新增可空category_id。供应商/仓库字段code、name、owner_id、department_id、active，供应商另有可空contact和phone。写入需要相应字段write权限。关联分类必须可读且ID可见；环形分类关系拒绝。已有策略不会因迁移自动获得新资源或新字段权限。

采购单、入库、库存、业务配置API尚未开放；数据库已预留不代表接口已完成。未知资源保持404。
