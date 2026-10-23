# 可选 AI 助手与受控查询网关

[文档导航](README.md) · [版本日志](version.md)

## v1.0.9 已实现范围

本阶段交付只读AI辅助解析，默认关闭。离线固定命令/本地规则始终优先；本地已识别的描述不会调用模型。用户明确同意后，仅发送本次输入与静态意图格式，不发送任何数据库记录、用户角色、业务配置或隐藏字段。模型只生成标准结构化意图，返回后还需用户确认查询；模型输出不执行SQL、代码或写入业务。

### 数据关系（编写业务代码前确认）

| 表               | 关键字段                                                                                                                                    | 关系/用途                                                                                                |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| ai_configuration | id=1、version、enabled、base_url、model、timeout_seconds、tools                                                                             | 单企业可选模型配置，默认关闭；不保存API密钥                                                              |
| ai_request       | id、version、owner_id、session_digest、config_version、request_key、payload_digest、state、intent、error_code、expires_at、lease_expires_at | owner→erp_user，session_digest→session_token；只保存校验后的意图，不保存原始描述、模型原始响应或查询结果 |

新增独立df2b1c0d9e8f迁移，不修改已发布迁移。用户与request_key唯一，原描述/同意/配置版本摘要绑定参数；同一会话相同键重试只返回当前可见请求，不重复调用模型，参数冲突409，处理中409，过期租约回放转失败。请求状态为parsing→ready/clarification/failed，用户可取消；过期按服务端UTC判断。低置信度仅提示重写，不能执行。解析租约限制同时进行的模型请求：每用户1个、全企业2个，另外每用户每分钟最多5次。失败和进程崩溃后的租约不会永久占用配额。

### 依赖与事务

Web→ai_api→ai_service→白名单HTTP模型适配器或ai_gateway→原业务服务/权限引擎→数据库。初始授权、模型完成后保存、确认查询分别使用短Gate事务；模型网络调用期间没有数据库事务或Gate锁。完成后重新检查原会话、用户、当前策略、配置版本/开关、租约和请求归属。超时/取消/停用/撤权不会执行查询。模型不可用不影响传统ERP。

### 授权

ai_configuration支持read/update；ai_requests支持read/create/execute/cancel且永远额外限定当前用户与原会话。intent字段控制可写描述解析与可读预览，执行要求完整预览可读并检查execute。inventory_balances/purchase_orders/sales_orders增加独立ai_query动作。工具取read∩ai_query，行范围、字段最严约束、明确拒绝与待审批均生效；销售汇总另需report。关联资料沿用原Web可读约束，不能由模型提供user_id、role、SQL、代码、任意URL或扩大范围。

| 工具                  | 标准意图资源    | 应用服务                                                 |
| --------------------- | --------------- | -------------------------------------------------------- |
| query_inventory       | inventory       | 同Web/OneBot库存查询，最多20条、当前字段投影             |
| query_purchase_orders | purchase_orders | 同Web/OneBot采购查询，最多20条、金额字段联动             |
| query_sales_summary   | sales_summary   | v1.0.8销售报表服务，保留来源/字段/币种/规模与SQL超时约束 |

工具结果直接展示给当前用户，不回传模型、不持久缓存。管理员工具开关只是上限，不能替代用户数据权限。确认查询重新检查策略和配置，不使用解析时的授权结果。查询为只读，重复确认重新查询当前可见数据。

### 网络与密钥

部署侧AI_ALLOWED_BASE_URLS显式列出允许的兼容服务地址（JSON数组，默认[]）；Web只能选择该白名单中的地址。拒绝URL凭据、query/fragment、重定向和环境代理。HTTP端点也须显式列入白名单，应只用于可信内网；域名解析与网络出口由部署管理员管理，不在运行时猜测网络归属。API密钥仅从服务端AI_API_KEY读取，Web只展示是否配置，数据库/日志/模型输入不包含密钥；无需密钥的本地模型可留空。

兼容适配器使用chat/completions、json_object及明确JSON提示，仍对响应执行严格白名单schema校验，拒绝截断、refusal、tool_calls、未知参数、重复JSON键和非有限数。超时2至20秒、响应最多32KiB、无自动重试；失败只返回受限错误代码，不反射供应商响应。

协议参考：[OpenAI官方结构化输出文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)。JSON mode不等于业务schema校验，兼容服务是否支持这些参数需真实联调验证。

### 本阶段边界

不配置真实供应商或调用付费端点，使用隔离HTTP测试服务验证协议与真实业务查询；不声称模型语义准确率或生产模型已验收。AI写入采购/销售、多轮补充、OneBot AI接入、对话总结与更多工具留待后续版本。Harness仅用于开发辅助，不是产品AI运行依赖。

## 已实现 API

| 方法与路径                            | 用途                                                             |
| ------------------------------------- | ---------------------------------------------------------------- |
| GET /api/v1/ai/status                 | 当前登录用户读取开关状态，不暴露地址、模型或凭据                 |
| GET /api/v1/ai/configuration          | 按字段权限投影模型配置及部署允许地址                             |
| PATCH /api/v1/ai/configuration        | version + values，校验旧/新配置权限与乐观锁                      |
| POST /api/v1/ai/requests              | text + consent=true，必须提供ASCII Idempotency-Key（1至128字符） |
| GET /api/v1/ai/requests               | 本账号、本次登录会话最近20条请求，分页前应用权限                 |
| GET /api/v1/ai/requests/{id}          | 当前会话的授权预览                                               |
| POST /api/v1/ai/requests/{id}/execute | version，重新授权只读查询，不调用模型、不缓存业务结果            |
| POST /api/v1/ai/requests/{id}/cancel  | version，取消并清除已解析意图                                    |

请求有效期5分钟，解析租约为配置超时加10秒。ready才可确认；clarification/failed/cancelled或过期均拒绝查询。模型请求完成后版本递增；重复查询仍检查当前原会话、配置版本、工具、范围及字段。

未授权403或范围内不存在404；禁用/处理中/参数摘要冲突/版本变化409；过期410；参数422；频率/容量429；模型不可用、响应校验失败或超时502。错误不会反射供应商正文。原会话已注销/用户停用时401，模型结果不会持久化为可执行预览。

原始描述仅存在本次调用内存及显式同意的模型请求中；校验后的intent可能保留商品关键词/单号，属于企业业务数据，应纳入数据库备份与历史保留管理。没有自动清理策略。模型服务的数据保留与网络出口须由部署管理员配置，不能以协议兼容性代替供应商验收。
