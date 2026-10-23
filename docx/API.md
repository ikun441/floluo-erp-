# API 规范

[文档导航](README.md) · [版本日志](version.md)

/api/v1 前缀；FastAPI /openapi.json 为已实现接口的准确契约。未实现模块不注册伪接口。
认证使用 HttpOnly 会话 Cookie；GET /auth/me 返回当前用户；修改请求要求 X-CSRF-Token 与 csrf Cookie 配对并匹配会话摘要。登录接口校验 Origin（如提供）。凭据不放 localStorage。

错误：401 未认证/失效，403 权限/字段/CSRF，404 不存在或不可见记录（避免 ID 探测），409 版本/完整性冲突，422 schema 错误。响应含 X-Trace-ID，错误不返回内部异常或 SQL。

写入通过同一授权事务。策略发布采用 expected_revision 乐观版本；业务 PATCH 包含 version，旧版本返回 409。分页 limit 最大 100，固定 UUID id 排序。后续导出任务绑定用户与策略版本，执行与下载均重新授权。

## 已实现的采购资料接口

认证后GET `/api/v1/resource_catalog`返回资源注册表中的字段、动作和可用范围，仅含契约元数据，无业务记录。权限界面以此配置矩阵。

`categories`、`suppliers`、`warehouses`与`products`使用以下统一接口：

| 方法  | 路径                                   | 请求                                |
| ----- | -------------------------------------- | ----------------------------------- |
| GET   | /api/v1/{resource}?limit=50&after=UUID | 范围过滤后固定ID分页                |
| GET   | /api/v1/{resource}/{id}                | 不可见与不存在统一404               |
| POST  | /api/v1/{resource}                     | `{ "data": { ... } }`               |
| PATCH | /api/v1/{resource}/{id}                | `{ "version": 1, "data": { ... } }` |

分类字段name、parent_id；商品新增可空category_id。供应商/仓库字段code、name、owner_id、department_id、active，供应商另有可空contact和phone。写入需要相应字段write权限。关联分类必须可读且ID可见；环形分类关系拒绝。已有策略不会因迁移自动获得新资源或新字段权限。

采购专用接口如下。未知资源保持404。

## 采购 MVP（已实现）

下列专用接口使用扁平业务命令，不使用资料CRUD的data包装：

| 方法      | 路径                                                           | 功能                                      |
| --------- | -------------------------------------------------------------- | ----------------------------------------- |
| GET/POST  | /api/v1/purchase_orders                                        | 受限列表 / 创建草稿                       |
| GET/PATCH | /api/v1/purchase_orders/{id}                                   | 受限详情 / 完整草稿编辑，含version        |
| POST      | /api/v1/purchase_orders/{id}/submit                            | 提交审批，body含version                   |
| POST      | /api/v1/purchase_orders/{id}/approve                           | 独立审批，body含version                   |
| POST      | /api/v1/purchase_orders/{id}/cancel                            | 未入库单据取消，body含version             |
| POST      | /api/v1/purchase_orders/{id}/receive                           | 采购收货并记库存，必须提供Idempotency-Key |
| GET       | /api/v1/purchase_receipts、inventory_balances、stock_movements | 当前授权下的列表和详情                    |
| GET/PATCH | /api/v1/system_configuration                                   | 当前业务配置 / 按version局部更新values    |

采购草稿参数：supplier_id、currency（显式三位大写币种）、note、lines。每行包含product_id、quantity、unit_price；数量和价格使用十进制字符串或整数，拒绝JSON浮点。行金额必须精确到分，不能静默舍入。所有者、部门、单号、状态、总额由服务端决定。PATCH同样要求完整草稿字段和version，且仅draft可编辑。

收货参数：version、warehouse_id、lines；每行line_id必须来自当前订单，quantity不得超过未收数量；每次请求至少一行，不允许重复行ID。Idempotency-Key按当前用户隔离、限制128个可打印ASCII字符。相同键/相同规范化命令重放返回已有收货单，重新授权并使用当前字段投影；不同内容返回409。重试必须保留首次version及其他命令字段。成功写入但缺少读取相关单据的权限时，只返回saved=true；重放无当前权限时拒绝，绝不重复加库存。

库存余额和流水没有创建、修改、删除API。列表上限100，固定ID游标；传入after时仅对ID可读记录分页，防止隐藏ID的游标探测。采购单列表在LIMIT前同时过滤供应商与所有明细商品的可见性；收货和流水进一步检查订单及仓库权限。

## v1.0.3 消息控制与查询入口

所有 Web 路由均要求现有会话，写入继续验证 CSRF/Origin，并在同一授权 Gate 事务内审计。QQ/bot ID 使用十进制字符串，拒绝额外身份字段。

- GET/POST `/api/v1/onebot_instances`：范围过滤的实例列表（最多100）；创建体 `{name, bot_id}`，返回 `{instance, access_token}`。令牌只在创建/轮换响应中出现，普通读取与模拟不返回令牌摘要。
- PATCH `/api/v1/onebot_instances/{id}`：`{version, active}`，当前不允许修改已建立实例的 bot ID。
- POST `/api/v1/onebot_instances/{id}/rotate_token`：`{version}`，返回一次新令牌并递增版本。
- GET `/api/v1/message_bindings`：仅当前用户且受策略过滤的绑定，最多100。
- POST `/api/v1/message_binding_challenges`：`{instance_id, platform_user_id, password}`，复核当前密码后返回 `{command, expires_at}`；挑战5分钟、指定实例/平台账号、单次使用。
- POST `/api/v1/message_bindings/{id}/revoke`：`{version}`，只允许撤销自身且具有 revoke 权限的绑定。
- WebSocket `/onebot/v11/ws/{instance_id}`：反向 Universal 接入，不使用 Web Cookie 授权。必须 Bearer 令牌与固定 bot 标识；详见 ONEBOT.md。当前业务工具只有只读采购/库存查询，写入意图不执行。

## v1.0.4 操作工作台

- GET `/api/v1/message_operations?state=&limit=50&after=`：仅自身且经策略过滤的元数据，limit≤100，游标要求ID可读。state只允许collecting_missing/awaiting_confirmation/completed/cancelled/expired。列表不直接返回业务结果ID。
- POST `/api/v1/message_operations`：`{values:{product?,supplier?,quantity?,unit_price?,currency?,unit?}}`，值均为字符串，最多6个白名单键（unit为本轮新增可选键）。无owner/role/resource等客户端身份参数；返回当前授权详情。
- GET `/api/v1/message_operations/{id}`：当前元数据、missing_fields及可授权preview/preview_digest；资料变化时刷新摘要与version，客户端不能沿用旧版本。终态按当前采购权限投影result/result_id。
- PATCH 同路径：`{version,values:{...}}`补充或修改等待态参数；不提交空字符串清除字段。
- POST `/api/v1/message_operations/{id}/cancel`：`{version}`。
- POST `/api/v1/message_operations/{id}/confirm`：`{version,preview_digest,password}`，经过现有会话、CSRF、Origin及密码复核，仅创建采购draft。重复确认使用原确认version/digest，重新授权后返回同一记录；不重复业务写入。

详情预览需要message_operations.preview可读及全部关键采购金额字段可读；更新参数需preview可写，取消/确认需state可写。409用于旧版本/旧摘要/终态冲突，403用于当前授权、绑定或预览不足。请求固定10分钟，单用户最多20条等待态。密码复核限流/锁定沿用统一认证保护。详见OPERATIONS.md。

## v1.0.5 离线解析接口

以下三个POST均只接受`{text: string}`，1–4096字符，拒绝额外键；要求当前会话与CSRF/Origin。没有数据库字段、SQL、身份或模型参数入口。

- `/api/v1/intents/parse`：只返回`{intent,missing}`，intent包含operation/resource/arguments/references/confidence/parser_source；不查询业务数据，不生成请求或订单。
- `/api/v1/intents/query`：后端重新解析且只允许query，复用当前用户采购/库存受控查询，最多20条，统一数据范围及字段投影。
- `/api/v1/intents/requests`：后端重新解析且只允许采购create，复用持久化请求和当前权限；仅返回请求详情。仍须原有confirm接口复核密码才能创建draft。

不识别/类型不匹配为422；单位不可读或与商品不一致统一422 quantity_unit_unresolved。规则与边界详见[INTERACTION.md](INTERACTION.md)。不增加新角色权限，也不会扩展旧角色授权。

## v1.0.5 只读消息监控

- GET `/api/v1/onebot_connections?limit=50&after=&state=`：state为connected/disconnected，limit≤100；返回当前可见实例的连接元数据。连接UUID/凭据不暴露；state=connected还须结合lease_expires_at确认有效。
- GET `/api/v1/message_deliveries?limit=50&after=&state=`：state为pending/awaiting_ack/delivered/failed/suppressed/expired；仅返回当前允许的元数据，不能获取recipe、收件人、原文或业务结果。

分别要求新资源onebot_connections/message_deliveries的read，并且关联实例ID当前可读；数据范围在分页前过滤，按状态/ID筛选需相应字段可读。没有通用详情或写入/强制补发接口。日期在投影后输出UTC ISO8601；过期按受限维护推进。已有角色需显式授权，新bootstrap为当前资源建立策略。

## v1.0.6 客户与销售

- GET/POST `/api/v1/customers`，GET/PATCH `/api/v1/customers/{id}`：通用受限目录，创建体`{data:{code,name,owner_id,department_id?,contact?,phone?,active?}}`，更新体`{version,data:{...}}`。复用数据范围、字段写入/投影、版本校验及审计；无物理删除。
- GET `/api/v1/sales_orders?limit=50&after=&status=`：limit≤100，status仅draft/submitted/approved/cancelled；状态筛选须status可读、游标须id可读，SQL在分页前过滤客户和所有商品引用。
- POST `/api/v1/sales_orders`：`{customer_id,currency,note?,lines:[{product_id,quantity,unit_price}]}`，最多100行，数量/价格只接受十进制字符串或整数。后端生成单号/归属/状态/总额，不接受额外身份字段。
- GET/PATCH `/api/v1/sales_orders/{id}`：受限详情/完整草稿编辑，PATCH另需version。金额total/unit_price/line_amount按最严格字段策略共同隐藏或脱敏。
- POST `/api/v1/sales_orders/{id}/submit|approve|cancel`：`{version}`，当前权限与旧/新状态均校验；销售创建人不得自批。提交/审批要求币种和no_tax配置；未配置409。当前无销售出库、删除、导出或AI/OneBot销售工具接口。

写入与outbox/审计同事务，写入成功但缺少读取权限时只返回`{saved:true}`；所有路由使用相同会话/CSRF/Origin/Gate边界。升级需显式给旧角色授权customers/sales_orders。

## v1.0.7 销售出库与库存方向

| 方法 | 路径                                                | 请求与行为                                                                         |
| ---- | --------------------------------------------------- | ---------------------------------------------------------------------------------- |
| POST | `/api/v1/sales_orders/{id}/ship`                    | Header `Idempotency-Key`；body `{version,warehouse_id,lines:[{line_id,quantity}]}` |
| GET  | `/api/v1/sales_shipments?limit=50&after=&order_id=` | 当前可读出库单，limit≤100，按ID游标分页                                            |
| GET  | `/api/v1/sales_shipments/{id}`                      | 当前可读发货单及受保护明细                                                         |

出库明细最多100行，至少一行；line_id必须属于当前订单，不能重复，quantity为正数十进制字符串或整数（最多4位小数），拒绝float/bool/额外身份字段。按商品合计需求后整体校验，任一行超计划或库存不足409，库存不存在或数量不可读统一404 inventory_unavailable。订单/仓库ship及发货create、字段/引用权限均校验，待审批策略不能直接执行。

幂等键为1–128可打印非空ASCII字符，按当前用户/销售出库命名空间隔离。相同原version/仓库/规范化明细重放返回已有发货单的当前投影，不再次扣库存；不同内容409。重放仍需当前ship/create及来源读取授权；原配置/资料停用不会重写历史。新发货无回读权限只返回saved，重放无读取权限403。

sales_orders状态筛选新增partially_shipped/shipped；lines中shipped_quantity由新增同名虚拟字段权限控制，未授权隐藏、masked脱敏。sales_shipments的order_id筛选、id游标须相应字段可读。当前无发货编辑/删除/强制重发接口。

stock_movements的quantity继续为正数：purchase_receipt增加，sales_shipment扣减，按kind和receipt_line_id/shipment_line_id唯一来源约束关联。查询在LIMIT前应用两种业务来源的权限；库存页展示类型方向，不返回未经授权的销售记录或价格。

## v1.0.8 基础报表

GET `/api/v1/reports/{inventory|movements|purchases|sales}` 返回items/columns/source_rows/policy_revision/scope/limits；GET同路径`/export`下载UTF-8 BOM CSV。全部读取当前会话身份。metric=count|amount（金额仅订单），库存/流水支持warehouse_id/product_id，流水另支持kind，订单支持status/currency。参数白名单、种类/长度校验，未知参数422。

统计取read与report交集，导出再取export；聚合前执行业务来源范围、关联和字段约束，金额字段联动。无动作允许规则403；当前可统计行为空则200空items/仅CSV表头。来源超过10000或分组超过200整体422，超时503，不返回部分汇总。成功审计仅元数据；错误沿用统一失败审计。详见[报表说明](REPORTS.md)。

## v1.0.9 可选AI与受控查询

新增`/api/v1/ai/status`、`/configuration`、`/requests`及请求详情/execute/cancel，完整契约见[AI说明](AI.md)。默认禁用，POST解析要求text、consent=true和Idempotency-Key；本地可识别的描述返回ai_local_available，不调用模型。配置PATCH使用version与部分values，先验证旧/新候选和字段写权限。

解析返回标准结构化意图与ready/clarification/failed等状态，确认只支持库存、采购查询与销售汇总。模型网络I/O外置于短授权事务之间；完成与执行分别重查当前会话/权限/配置。execute只返回当前业务服务投影，不把结果交回模型。所有POST/PATCH仍需CSRF/Origin校验。参数验证若早于事务依赖，失败审计兜底只记录模板路径、身份和422；既有事务已记录的错误不会重复记账。

## v1.0.10 AI采购补全与移交

PATCH /api/v1/ai/requests/{id} 接收version和非空values（product/supplier/quantity/unit_price/currency/unit字符串），只修改当前原会话的结构化意图，最多10次，按旧/新update字段授权。POST /api/v1/ai/requests/{id}/prepare 接收version，要求prepare与当前采购create∩ai_prepare，原子创建最多一个message_operation，返回{request, operation}；重试使用原接受版本，不创建订单。查询execute拒绝create意图。之后普通message_operations确认仍需当前密码与摘要；该明确人为移交后的流程不依赖AI开关。
