# 架构、数据与权限

[文档导航](README.md) · [版本日志](version.md) · [当前验收](IMPLEMENTATION.md)

当前范围以实施记录为准；下文保留必要的架构、升级与历史依据。

[架构与模块边界](#architecture) · [数据库模型与迁移](#database) · [统一权限引擎](#permissions)

<a id="architecture"></a>

## 架构与模块边界

<a id="architecture-部署与模块边界"></a>

### 部署与模块边界

Linux / Nginx → Next.js Web、FastAPI REST / WebSocket → 统一应用服务 → 权限决策 + 业务领域 → SQLAlchemy / PostgreSQL。
Celery + Redis 规划用于通知、AI 超时任务、报表任务，当前核心启动无此必需依赖；事务 outbox 发布已提交事件，业务正确性不依赖队列在线。
Redis 不作为库存或授权真相来源。AI 与消息协议可独立关闭，核心 Web 不依赖外网。

模块依赖：identity → authorization → catalog → procurement → inventory；sales 依赖 catalog/inventory；workflow 通过应用命令触发并重新授权；audit 为基础设施横切能力。adapters(onebot/web/ai_tools) 仅调用 application，不反向依赖 adapter。

<a id="architecture-一致性"></a>

### 一致性

Phase 1 采用数据库 authorization_gate 单行锁，事务入口获取后加载用户、角色、当前策略与资源并完成操作、审计和提交。此保守实现串行化请求，优先保证撤权与写入的严格顺序，后续在 PostgreSQL 并发测试支持下细化为共享授权锁 + 资源行锁。
库存现已使用 warehouse/product balance 行锁、不可变流水、业务来源唯一键、幂等键和 outbox 同事务提交。异步任务执行前重新授权，不沿用排队时的允许结果。

<a id="architecture-状态机"></a>

### 状态机

采购：draft → submitted → approved → partially_received → received；draft/submitted/approved可在未入库时取消；通用撤回与冲销尚未实现。具体退货、超收和金额规则待确认，未配置时拒绝。
审批：pending → approved/rejected/withdrawn/expired。审批通过只授权重新提交相同摘要的命令，不自动扩大申请人权限。

<a id="architecture-安全与运行"></a>

### 安全与运行

服务端会话，Argon2 密码，Cookie HttpOnly/Secure/SameSite，修改请求 CSRF，来源校验。策略版本与用户状态由数据库实时读取。日志使用 trace id，严禁密码、AI 密钥、消息原文默认落日志。
采用显式资源注册表和条件 AST，禁止运行时任意 Python/SQL 插件。模块注册包含资源字段、允许动作、服务入口和命令 schema。

<a id="architecture-技术依据"></a>

### 技术依据

FastAPI 密码哈希参考 https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ ；SQLAlchemy 并发版本参考 https://docs.sqlalchemy.org/en/20/orm/versioning.html 。服务端会话用于可即时撤销认证，避免把角色写入长期令牌。

<a id="architecture-phase-2落地"></a>

### Phase 2落地

procurement_api仅适配请求/响应，procurement服务统一执行草稿、提交、审批、取消、入库；复用当前事务、身份和权限引擎。每次请求先锁authorization_gate，订单/行/余额再按稳定顺序锁定。收货、收货行、不可变流水、余额、幂等记录、订单状态、outbox及成功审计同事务提交；失败先回滚，再独立追加失败审计。意外异常同样尝试记录500；若数据库本身不可用，仅输出无参数的追踪日志，不能保证数据库审计落盘。

当前库存服务只支持采购入库，尚不实现销售出库、退货、成本核算或冲销。outbox是持久化待处理记录，未连接消息消费者，不返回虚构通知成功。系统无需Redis/AI/OneBot即可完成当前Web采购流程。

<a id="architecture-v103-消息切片"></a>

### v1.0.3 消息切片

OneBot transport → message_gateway（Gate、事务、收件箱和审计）→ message_service（绑定/受控查询）→ 已有采购范围与投影/权限引擎。适配器不读写数据库、不解释ERP角色。Web messaging_api调用相同身份服务和统一权限资源。当前只实现反向Universal与私聊只读工具，AI和消息写入不参与核心启动。

<a id="architecture-v104-预览与执行分离"></a>

### v1.0.4 预览与执行分离

Web/OneBot → message_operations应用服务 → procurement.prepare_draft纯计划/统一权限 → Web密码复核后procurement.draft。预览与执行共用校验逻辑，参数及引用版本摘要将用户所见与提交内容绑定；版本或绑定变化后重新预览。MessageOperation持久化收集/确认/取消/过期/完成状态，消息适配器不直接写业务数据。新增操作工作台连接真实API；版本日志迁至docx/version.md。

<a id="architecture-v106-客户与销售基础"></a>

### v1.0.6 客户与销售基础

SalesView → sales_api → sales → order_support + Engine → sales_models/PostgreSQL。客户资料使用同一受限目录服务，权限字段/动作通过注册表驱动权限中心。order_support仅提取原有受限引用、配置、版本、线格式及outbox工具；procurement保留导入兼容，不改变其调用契约。销售和采购共享币种/税配置，销售始终独立审批；销售订单只进入草稿/提交/批准/取消状态，本切片不变动库存。未来出库复用库存领域事务，不直接改余额。详见SALES.md。

<a id="architecture-v107-销售出库"></a>

### v1.0.7 销售出库

SalesView/ShipmentEditor → sales_api → shipment应用服务 → 当前订单/授权/库存行锁。审批只批准订单，实际发货才扣库存；发货、明细、不可变方向流水、余额、订单进度、幂等、outbox和审计同事务。当前Gate仍串行化授权与业务命令，行锁以订单/销售行/商品稳定排序，未来细化Gate前须保留真实PG争抢库存测试。

已有库存读取入口兼容采购与销售两种来源，在SQL分页前分别约束对应订单、客户/供应商、商品、仓库和来源单据ID。协议/AI未新增出库工具，仍不能直接操作库存。详见[出库服务边界](BUSINESS.md#shipments)。

<a id="architecture-v108-只读报表服务"></a>

### v1.0.8 只读报表服务

ReportsView→reports_api→reports→既有procurement/sales查询与Engine.field_scope→数据库，复用Gate事务、会话、审计。只有白名单报表/指标/维度，SQL先授权再限规模和聚合，不加载完整订单/逐行N+1，不建立报表数据副本。CSV再走相同服务并加入export交集，无AI、队列或新表依赖。当前同步有界统计；异步导出、日期趋势与BI后续单独设计。

<a id="architecture-v109-ai边界与事务"></a>

### v1.0.9 AI边界与事务

AIAssistantView/AIConfigurationView→ai_api→ai_service→ai_client或ai_gateway→原message_service/reports→统一Engine/SQL。ai_client只接触本次输入、静态格式与部署凭据，不接触Session或业务模型；ai_gateway只接受严格白名单AIIntent和服务端当前主体。

模型解析采用“短事务登记/授权并提交→无DB事务的有界HTTP→短事务重新认证/授权并保存”流程，网络期间不占Gate。全企业2个/每用户1个进行中配额与每分钟5次计数来自同一数据库，幂等键避免响应丢失后再次调用模型。取消、租约过期、会话撤销、配置变化与权限变更均禁止旧调用完成或执行。

只读工具结果直接展示在ERP，重复确认重新查询；模型不会接收业务记录或结果总结。本版不引入模型必需的Celery/Redis/云服务。AI写入、多轮补充和消息平台AI接入后续单独实现。

<a id="architecture-v1010-采购意图与人工流程"></a>

### v1.0.10 采购意图与人工流程

intent.py中的纯normalize_purchase_values为离线、AI schema及操作工作台共用。AIIntent只允许查询或单商品采购create；补全与移交无网络调用。ai_handoff建立AI请求到既有message_operation的一对一关系，Gate事务内以create∩ai_prepare验证候选，最多移交一次。明确接受后的人工流程复用原摘要、引用版本、当前密码和草稿幂等服务，不反向依赖AI开关。

<a id="database"></a>

## 数据库模型与迁移

本文件先于业务实现建立。Phase 1 迁移只创建 identity、authorization、audit 与商品基础切片；Phase 2已迁移采购/库存基础表，并已开放采购单、审批、入库和库存的真实接口。消息身份、收件箱、操作会话、回复/连接运行态及客户/销售表已落地；通用工作流仍为后续设计。

| 关系                                          | 约束与用途                                                         |
| --------------------------------------------- | ------------------------------------------------------------------ |
| department → department                       | parent_id 外键，服务层防环                                         |
| user → department / position / user           | 所属部门、岗位、直属主管；引用 RESTRICT                            |
| user ↔ role                                   | user_role 复合主键，一个用户多角色                                 |
| policy_revision → policy rules                | 不可变 JSON AST 快照，版本唯一，author 外键                        |
| authorization_gate → policy_revision          | singleton 当前版本 + 事务锁；禁止删除                              |
| session → user                                | 随机 token 仅存 SHA256，过期、撤销、CSRF 摘要                      |
| auth_throttle                                 | 来源哈希，失败计数与锁定时间                                       |
| product → user / department                   | 所有者与所属部门用于数据范围                                       |
| audit_event → previous audit_event hash       | 全局串行追加摘要链，应用不支持修改/删除                            |
| purchase_order → supplier / department / user | 单号唯一、NUMERIC 总额、状态、版本                                 |
| purchase_line → purchase_order / product      | 正数数量、非负单价，金额服务端计算                                 |
| receipt_line → purchase_line / warehouse      | 收货分摊、唯一业务来源防重复                                       |
| inventory_balance → warehouse / product       | 复合唯一，NUMERIC 数量与版本                                       |
| stock_movement → product / warehouse / source | 正数数量，kind区分采购增加/销售减少；采购/销售来源互斥，冲销待后续 |
| message_binding → instance / user             | 平台身份与实例复合唯一，验证挑战、撤销状态                         |
| message_inbox / command_execution             | 平台事件唯一键、用户幂等键、payload 摘要                           |
| conversation → binding / intent               | 状态、过期时间、确认摘要、版本                                     |
| workflow_revision / approval / approval_event | 定义快照、申请摘要、审批人与操作不可变记录                         |
| outbox → aggregate                            | 事务内事件，发送可重试，消费端幂等                                 |

所有业务标识采用 UUID；金额 NUMERIC(18,2)，数量 NUMERIC(18,4)，UTC DateTime(timezone=True)。所有 FK 建立访问索引。业务行包含 created_at、updated_at、version；DB FK、唯一、CHECK 约束是第二道一致性边界。

关系示意：user ← user_role → role；gate → revision → rules(subject → resource/action/scope/fields/conditions)；user/department → product。业务扩展由 purchase_order → lines → receipts → stock_movement → balance 形成闭环。

Phase 1 审计使用 SHA256 串联，能检测链内修改，不能抵御数据库所有者重写整链或裁剪尾部。生产应由外部可信介质定期保存链头签名/锚点；应用数据库角色无 UPDATE/DELETE/TRUNCATE 权限。

Phase 2具体关系、精度、状态与幂等规则见PROCUREMENT.md；新增采购、收货、流水、余额、命令幂等、业务配置和outbox表；审计新行采用v2摘要，旧链摘要不重写。

<a id="database-v103-消息身份与收件箱"></a>

### v1.0.3 消息身份与收件箱

- `onebot_instance`：独立协议实例，固定 bot_id、启用状态和仅存摘要的连接令牌。令牌轮换使旧连接在下一帧失效。
- `message_binding`：实例与平台用户映射到 ERP owner_id；(instance_id, platform_user_id) 与 (instance_id, owner_id) 均唯一，停用记录保留。平台群角色不参与授权。
- `binding_challenge`：Web 当前用户经密码复核后，为指定实例和预期平台用户签发5分钟单次挑战；只存摘要，兑换时检查范围、有效期、当前用户与策略。
- `message_inbox`：event_key 主键、实例外键、payload_digest、结果和处理时间；不保存原文、绑定码或查询结果。事件处理、绑定变更、收件箱结果和审计同事务；重复事件不执行、不重发旧结果，同键不同内容拒绝。

关系：OneBotInstance 1—N MessageBinding N—1 User；OneBotInstance 1—N BindingChallenge N—1 User；OneBotInstance 1—N MessageInbox。先持有 authorization_gate 再访问这些记录，策略与消息操作共享现有事务授权边界。新资源默认拒绝，升级不自动扩大原有策略。

<a id="database-v104-消息操作会话"></a>

### v1.0.4 消息操作会话

新增 `message_operation`：Row UUID/UTC时间/version；owner_id → User，binding_id → MessageBinding，保存签发时binding_version；resource固定purchase_orders；payload仅存白名单采购参数，不存原始消息、密码或连接令牌；target_order_id唯一预留ID，result_id → PurchaseOrder且唯一；状态 collecting_missing / awaiting_confirmation / completed / cancelled / expired；expires_at；preview_digest覆盖引用资料版本。

Web发起时binding_id/binding_version为空，消息发起时保存有效绑定版本。One MessageBinding 1—N MessageOperation；User 1—N MessageOperation；完成的MessageOperation 1—1 PurchaseOrder。创建请求不创建订单。预览用同一非写入采购校验计划构建，执行仍走采购服务。确认同时检查会话version、摘要、当前绑定、当前主体/策略、引用资料版本，订单/会话完成/outbox/审计同事务。完成回放不得重复写入，结果按当前权限投影。只有归属用户可查看/补充/取消/确认，仍需统一策略授权；过期按访问时推进，不引入后台服务必需依赖。含任何新会话数据时拒绝破坏性迁移降级。

<a id="database-v105-回复投递与连接运行态已实现"></a>

### v1.0.5 回复投递与连接运行态（已实现）

onebot_instance 1—0..1 onebot_connection；message_inbox 1—0..1 message_delivery（event_key唯一外键）。message_delivery同时关联实例、可空用户和版本化绑定快照。回复只持久化受限recipe，不持久化结果正文，终态清除recipe。连接UUID作为跨进程租约栅栏，单实例仅一个未过期拥有者。新表、状态约束、外键与队列索引通过新迁移添加，旧表与迁移不改动。完整字段、状态、权限和失败语义见[DELIVERY.md](INTERACTION.md#delivery)。

<a id="database-v106-客户与销售订单"></a>

### v1.0.6 客户与销售订单

新增be0f9a8b7c6d（继承ad9e8f7a6b5c）：customer唯一编码/归属外键，sales_order客户/归属/审批人外键、唯一SO单号、非负NUMERIC总额及状态/审批人配对约束；sales_line订单/商品外键、订单内行号唯一、正数数量和非负金额。均包含UTC时间/version及FK索引。既有表、迁移、库存来源约束和策略快照不改动，不造业务资料；存在客户或销售历史时拒绝破坏性降级。完整ER关系与安全默认见SALES.md。

<a id="database-v107-发货与方向流水"></a>

### v1.0.7 发货与方向流水

迁移ce1a0b9c8d7e新增sales_shipment、shipment_line、shipment_execution。销售行shipped_quantity默认0并受0≤已发≤计划约束；订单支持partially_shipped/shipped且保留审批人约束。发货/发货行/命令记录采用追加存储，PG阻止UPDATE/DELETE/TRUNCATE，SQLite阻止UPDATE/DELETE。

stock_movement新增唯一shipment_line_id外键，receipt_line_id变可空；ck_stock_movement_source要求kind与唯一业务来源配对。原正数数量检查、旧采购流水、唯一/外键/索引和不可变触发器均保留。出库历史存在时拒绝破坏性降级；无出库时可回退至be0f9a8b7c6d并保留旧采购/销售数据。SQLite重建显式保留未命名检查约束，并在事务前后检查外键。完整关系见[出库设计](BUSINESS.md#shipments)。

<a id="database-v108-只读报表"></a>

### v1.0.8 只读报表

复用库存余额、方向流水及采购/销售单据，没有新增业务表或列，因此无新迁移，迁移头保持ce1a0b9c8d7e。report/export是资源动作目录扩展，已发布策略快照不改动。授权与来源关联过滤后，在受限子查询上按仓库/商品/方向或状态/币种分组，保留NUMERIC精度，不跨币种/单位合计。

<a id="database-v109-可选ai请求与配置"></a>

### v1.0.9 可选AI请求与配置

新增独立迁移df2b1c0d9e8f，继承ce1a0b9c8d7e，不修改既有业务表。

| 表               | 约束与关系                                                                                                     |
| ---------------- | -------------------------------------------------------------------------------------------------------------- |
| ai_configuration | 单行id=1，version乐观锁，默认disabled、空URL/model/tools，timeout_seconds限制2至20；密钥不入库                 |
| ai_request       | owner_id→erp_user、session_digest→session_token，用户/请求键唯一；config_version保存配置快照号，非历史配置外键 |
| ai_request 状态  | parsing/failed/cancelled时intent为SQL NULL，ready/clarification时必须有校验后的JSON意图                        |
| ai_request 索引  | owner_id+created_at用于近期列表/频率，state+lease_expires_at用于进行中配额                                     |

请求另保存参数摘要、原会话、5分钟过期时间、网络租约和受限错误码，不保存原始描述、供应商响应、API Key或查询结果。原有Gate保护初始登记和完成写回；HTTP期间没有数据库事务。已存在请求历史时拒绝破坏性降级，空请求表可显式退回ce1a0b9c8d7e；配置会随该降级删除，需先备份。PostgreSQL/SQLite均验证迁移元数据一致性。

<a id="database-v1010-单次采购移交"></a>

### v1.0.10 单次采购移交

ai_handoff(request_id PK/FK→ai_request, operation_id UNIQUE/FK→message_operation, source_version>=1, created_at timestamptz)。独立迁移e03c2d1e0f9a，保留全部旧表与历史。Gate与唯一约束防并发重复移交；请求版本与待确认操作同事务提交。存在AI请求历史拒绝降级，避免旧版本不识别新create意图。

<a id="permissions"></a>

## 统一权限引擎

接口 authorize(subject, action, resource, context) 返回 allowed、reason、scope、fields、requires_approval、policy_ids、revision。

1. 主体由已验证会话读取 user、department、roles；不接受请求中的角色冒充身份。管理员也只依赖已配置策略，无代码内 superuser 分支。
2. 策略主体匹配 user/role/department；action/resource 精确匹配。数据范围 own/department/departments/all/records。
3. 条件采用字段白名单 AST（eq、in、lt、lte、gt、gte），禁止表达式解释器。未知字段、操作符和缺失上下文拒绝；条件同一规则取 AND。
4. 列表 SQL = OR(allow predicates) AND NOT OR(deny predicates)，必须在 LIMIT、分页前过滤。详情、创建、修改采用相同条件编译器。
5. 无允许默认拒绝，任何匹配的 deny 拒绝。多条 allow 的字段权限取最严格结果：hidden > masked > read > write。未声明字段 hidden；读响应必须投影，写入必须逐字段许可。
6. 创建检查新数据，修改同时验证旧状态与新状态。requires_approval 未具备审批回执时禁止执行，不能把“需要审批”当作允许直接写入。
7. 策略整体版本化发布，不修改历史 revision。所有事务先锁 gate，再读当前版本，故不缓存策略，不存在旧缓存允许。该基础版本吞吐量有限，优化前必须有 PostgreSQL 并发撤权测试。
8. 模拟器与真实服务使用同一引擎，模拟本身也需要授权，避免泄露其他用户策略。冲突报告保守报告相同资源/动作的 allow/deny 重叠可能性，不声称证明策略无冲突。
9. 初期只提供固定 id 排序与有界分页，不允许按隐藏字段排序/筛选。后续统计、导出、AI 工具均复用受限查询，不对未授权集合做聚合。

示例：采购员角色对 purchase_order 的 update/own + status=draft 允许，另一条 deny 对 status=approved 拒绝；无论入口是 Web 或 OneBot 都得到相同结果。

采购资料扩展：categories不提供own/department范围；suppliers和warehouses支持所有者与部门范围。字段和动作由认证后的resource_catalog提供。升级不会重写已有策略：授权管理员应在权限中心显式增加新资源规则，并按需要开放products.category_id；创建校验包含schema默认字段，未开放新字段时创建可能被拒绝。初始化新数据库时bootstrap会对当前已注册资源生成明确的数据策略，不存在管理员绕过。

分类关联同时检查目标记录和目标ID的可读性。没有分类ID读取权限时，商品category_id和分类parent_id不会间接泄露该ID。关联写入使用同一事务内的当前策略检查。版本条件同时验证更新前版本和将要保存的新版本。

采购资源已注册：purchase_orders（read/create/update/submit/approve/cancel/receive）、purchase_receipts（read/create）、inventory_balances与stock_movements（read）、system_configuration（read/update）；warehouses新增receive动作。旧策略不自动扩权，升级后请显式配置新规则。

采购单lines、unit_price、line_amount属于登记的虚拟字段，可配置字段权限但不能作为SQL条件。金额条件支持真实NUMERIC列，例如`{"field":"total","op":"gt","value":"5000.00"}`，金额阈值必须为有限十进制字符串或整数。禁止虚拟字段、任意表达式或SQL条件。

读取采购金额时，total、unit_price、line_amount取最严格可见级别并联动投影；任何一项隐藏则全部不返回，任何一项脱敏则全部脱敏，防止反推。创建/编辑订单需要supplier_id、currency、note、lines、unit_price的write权限；派生状态和总额由独立动作与业务规则控制。读关联ID要求对应资源ID也可读。

基础采购审批使用明确状态机和approved_by，不是通用审批工作流。requires_approval=true的策略仍阻止执行，直到后续通用审批回执机制完成；采购状态批准不会自动绕过该标志。模拟器只展示权限决策，业务状态、币种/税规则、自审批限制在服务中另行检查。

<a id="permissions-v103-消息资源"></a>

### v1.0.3 消息资源

新增 onebot_instances（read/create/update/rotate_token）与 message_bindings（read/create/revoke/use，自身范围）。access_token 与 password 均为只写字段，策略拒绝 read/masked 模式，通用投影也永不返回这些字段。实例令牌创建/轮换仅在已获得明确令牌写权限的响应中返回一次。

实例连接认证与 ERP 绑定身份不同：可信协议源提供平台身份，单次挑战将其映射到 ERP 当前用户；每条业务查询重新构建 Subject 和策略引擎。消息查询复用采购/库存 SQL 范围与字段投影，用户无法提供角色/部门替代服务端主体。群聊不返回业务结果。升级不修改既有策略，新资源仍默认拒绝。

修正 requires_approval 的读取路径：SQL 列表范围排除任何匹配的待审批允许策略，详情投影同样拒绝；Web 与消息一致。在通用审批回执机制完成前，这类读取不返回记录。

<a id="permissions-v104-确认请求"></a>

### v1.0.4 确认请求

message_operations是独立注册资源，支持read/create/update/cancel/confirm、own范围。旧策略不自动增加权限。服务端始终限定当前owner；平台请求额外限定原binding ID/version，平台身份不能提供ERP主体。

preview字段控制参数写入与完整预览展示，state字段控制显式取消/确认。展示预览前重查业务create/read和引用范围；完整关键金额不可读时拒绝预览。刷新导致version变化后再次决策，避免旧读权限继续展示。业务result/result_id只在当前采购读取范围及字段投影允许时返回，列表不直接暴露result_id。created_at/expires_at/preview/result等虚拟字段不能用作SQL条件AST。

确认检查原参数摘要和资料版本并在创建后提交前复核；重放再次要求当前create权限并投影当前可见结果。requires_approval仍拒绝执行，不把请求确认当作通用审批。

<a id="permissions-v105-监控与投递"></a>

### v1.0.5 监控与投递

onebot_connections与message_deliveries仅有read；后者支持own/records/all，前者支持records/all。关联onebot_instances.id必须在当前可读范围，筛选state和游标id也需可读。监控不注册recipe、收件人、连接UUID/回执token或原文字段，不能经通用CRUD读写。旧角色必须显式增加新资源权限；前端隐藏不替代后端约束。

投递器是内部受限执行者，不能接受客户端角色/SQL/自由工具。业务回复每次按保存主体、平台收件人和绑定版本重建Engine，检查bindings.use后调用相同业务服务。只重建查询或已有请求视图，不重放创建/审批/入库。身份失效或请求授权不足抑制并清除recipe，读取权限变化按当前范围/字段重新过滤。

<a id="permissions-v106-销售资源"></a>

### v1.0.6 销售资源

customers复用目录read/create/update；sales_orders注册read/create/update/submit/approve/cancel，支持own/department/departments/records/all。只在新bootstrap显式生成策略，已发布快照不改动，升级需管理员在权限中心显式授予。sales_orders字段为订单ID/版本/单号/customer_id/owner_id/department_id/currency/total/status/note/approved_by/lines/unit_price/line_amount；后三者为虚拟字段，禁止SQL条件。

销售列表/详情在SQL中过滤当前客户和所有商品的可读ID，状态/游标探测须相应字段可读；金额三字段取最严格投影，不能从明细反推隐藏总额。编辑旧/新候选与实际提交字段均校验；状态迁移旧/新状态授权，requires_approval继续拒绝，独立审批不替代业务权限。创建归属取服务端当前身份。审批不产生库存权限或变动。

<a id="permissions-v107-出库授权矩阵"></a>

### v1.0.7 出库授权矩阵

| 资源/字段                     | 必需授权或用途                                    |
| ----------------------------- | ------------------------------------------------- |
| sales_orders.ship             | 发货前/后订单状态均授权，显式拒绝优先             |
| warehouses.ship               | 当前目标仓库有出库操作权限，且仓库ID可读          |
| sales_shipments.create        | 发货资源符合范围，order_id/warehouse_id/lines可写 |
| inventory_balances.read       | 目标库存当前id和quantity可读，否则统一404         |
| customers/products.read       | 客户及订单全部商品ID当前可读，本次发货引用须启用  |
| sales_shipments.read          | 查询/回放发货记录；范围与来源关系在分页前过滤     |
| sales_orders.shipped_quantity | 新增虚拟字段，控制各行已发数量；不允许SQL条件     |

旧策略快照不变，不自动增加ship动作、发货资源或已发字段。发货读取不返回订单金额；发货与库存流水的来源ID须当前可读，隐藏来源ID不能通过游标或关联绕过。回放重新校验当前ship/create和读取授权，不能取队列里的旧数据或重复执行扣减。库存余额/流水仍无通用写入接口。

<a id="permissions-v108-统计与导出"></a>

### v1.0.8 统计与导出

inventory_balances、stock_movements、purchase_orders、sales_orders新增report/export动作，旧策略不自动扩权。统计=read∩report，导出=read∩report∩export，各动作的范围、条件、显式拒绝、待审批和字段最严约束均在SQL聚合前应用。Engine.field_scope泛化原可读字段SQL过滤，readable_scope保持原契约。

库存要求warehouse_id/product_id/quantity，流水另需kind；关联商品id/sku/name/unit、仓库id/code/name必须完整可读。订单数量要求status/currency，金额要求三项total/unit_price/line_amount均完整可读；否则该行不参与对应指标，不返回排除行数。所有筛选/分组字段在授权后使用。既有来源单据关系约束继续生效。详见[配置与统计口径](BUSINESS.md#reports)。

<a id="permissions-v109-ai授权"></a>

### v1.0.9 AI授权

ai_configuration支持read/update；ai_requests支持read/create/execute/cancel，具备own范围，并额外强制owner与原session_digest相等。即使策略all也不能读取或确认另一账号/会话的请求。intent是虚拟字段，不允许SQL条件；完整预览必须id/version/state/intent可读，create要求intent可写，cancel要求state可写，execute另检查该动作的预览字段可读与待审批标志。

inventory_balances、purchase_orders、sales_orders增加ai_query。ToolEngine将主资源read与ai_query的行范围和字段权限取交集，显式拒绝和待审批优先；关联资料仍沿用既有Web读取约束。库存/采购最多20条，字段投影和金额联动与Web一致；销售汇总另需report，参与聚合字段必须完整可读。

管理员工具开关不能授予业务权限；模型不可传主体、角色、SQL、URL或额外参数。旧策略不增加新资源/动作，需在权限中心显式授权。预览不是授权凭证，完成与执行重查当前策略/用户/会话/配置/期限。失败与工具调用审计不记录原文、模型正文、数据单元格或密钥。详见[配置顺序与API](INTERACTION.md#ai)。

<a id="permissions-v1010-ai采购授权"></a>

### v1.0.10 AI采购授权

ai_requests增加update/prepare，字段增加operation_id虚拟投影；purchase_orders增加ai_prepare。工具开关prepare_purchase_draft默认不启用，旧策略不扩权。补全旧/新intent均需可写、完整预览可读；移交在原会话与配置版本下取采购create∩ai_prepare，金额、来源、本人范围、显式拒绝和待审批均检查。操作链接仅在当前操作read/id可读时返回。移交是接受参数进入普通人为流程的明确边界，后续继续按工作台权限、当前密码/摘要确认；不自动执行任何订单状态流转。策略每条动作数上限32，合法名称仍须属于资源注册白名单。
