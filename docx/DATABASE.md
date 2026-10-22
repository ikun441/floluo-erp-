# 数据模型与核心关系

[文档导航](README.md) · [版本日志](version.md)

本文件先于业务实现建立。Phase 1 迁移只创建 identity、authorization、audit 与商品基础切片；Phase 2已迁移采购/库存基础表，并已开放采购单、审批、入库和库存的真实接口。消息身份、收件箱、操作会话、回复/连接运行态及客户/销售表已落地；通用工作流仍为后续设计。

| 关系 | 约束与用途 |
| --- | --- |
| department → department | parent_id 外键，服务层防环 |
| user → department / position / user | 所属部门、岗位、直属主管；引用 RESTRICT |
| user ↔ role | user_role 复合主键，一个用户多角色 |
| policy_revision → policy rules | 不可变 JSON AST 快照，版本唯一，author 外键 |
| authorization_gate → policy_revision | singleton 当前版本 + 事务锁；禁止删除 |
| session → user | 随机 token 仅存 SHA256，过期、撤销、CSRF 摘要 |
| auth_throttle | 来源哈希，失败计数与锁定时间 |
| product → user / department | 所有者与所属部门用于数据范围 |
| audit_event → previous audit_event hash | 全局串行追加摘要链，应用不支持修改/删除 |
| purchase_order → supplier / department / user | 单号唯一、NUMERIC 总额、状态、版本 |
| purchase_line → purchase_order / product | 正数数量、非负单价，金额服务端计算 |
| receipt_line → purchase_line / warehouse | 收货分摊、唯一业务来源防重复 |
| inventory_balance → warehouse / product | 复合唯一，NUMERIC 数量与版本 |
| stock_movement → product / warehouse / source | 正数数量，kind区分采购增加/销售减少；采购/销售来源互斥，冲销待后续 |
| message_binding → instance / user | 平台身份与实例复合唯一，验证挑战、撤销状态 |
| message_inbox / command_execution | 平台事件唯一键、用户幂等键、payload 摘要 |
| conversation → binding / intent | 状态、过期时间、确认摘要、版本 |
| workflow_revision / approval / approval_event | 定义快照、申请摘要、审批人与操作不可变记录 |
| outbox → aggregate | 事务内事件，发送可重试，消费端幂等 |

所有业务标识采用 UUID；金额 NUMERIC(18,2)，数量 NUMERIC(18,4)，UTC DateTime(timezone=True)。所有 FK 建立访问索引。业务行包含 created_at、updated_at、version；DB FK、唯一、CHECK 约束是第二道一致性边界。

关系示意：user ← user_role → role；gate → revision → rules(subject → resource/action/scope/fields/conditions)；user/department → product。业务扩展由 purchase_order → lines → receipts → stock_movement → balance 形成闭环。

Phase 1 审计使用 SHA256 串联，能检测链内修改，不能抵御数据库所有者重写整链或裁剪尾部。生产应由外部可信介质定期保存链头签名/锚点；应用数据库角色无 UPDATE/DELETE/TRUNCATE 权限。

Phase 2具体关系、精度、状态与幂等规则见PROCUREMENT.md；新增采购、收货、流水、余额、命令幂等、业务配置和outbox表；审计新行采用v2摘要，旧链摘要不重写。

## v1.0.3 消息身份与收件箱

- `onebot_instance`：独立协议实例，固定 bot_id、启用状态和仅存摘要的连接令牌。令牌轮换使旧连接在下一帧失效。
- `message_binding`：实例与平台用户映射到 ERP owner_id；(instance_id, platform_user_id) 与 (instance_id, owner_id) 均唯一，停用记录保留。平台群角色不参与授权。
- `binding_challenge`：Web 当前用户经密码复核后，为指定实例和预期平台用户签发5分钟单次挑战；只存摘要，兑换时检查范围、有效期、当前用户与策略。
- `message_inbox`：event_key 主键、实例外键、payload_digest、结果和处理时间；不保存原文、绑定码或查询结果。事件处理、绑定变更、收件箱结果和审计同事务；重复事件不执行、不重发旧结果，同键不同内容拒绝。

关系：OneBotInstance 1—N MessageBinding N—1 User；OneBotInstance 1—N BindingChallenge N—1 User；OneBotInstance 1—N MessageInbox。先持有 authorization_gate 再访问这些记录，策略与消息操作共享现有事务授权边界。新资源默认拒绝，升级不自动扩大原有策略。

## v1.0.4 消息操作会话

新增 `message_operation`：Row UUID/UTC时间/version；owner_id → User，binding_id → MessageBinding，保存签发时binding_version；resource固定purchase_orders；payload仅存白名单采购参数，不存原始消息、密码或连接令牌；target_order_id唯一预留ID，result_id → PurchaseOrder且唯一；状态 collecting_missing / awaiting_confirmation / completed / cancelled / expired；expires_at；preview_digest覆盖引用资料版本。

Web发起时binding_id/binding_version为空，消息发起时保存有效绑定版本。One MessageBinding 1—N MessageOperation；User 1—N MessageOperation；完成的MessageOperation 1—1 PurchaseOrder。创建请求不创建订单。预览用同一非写入采购校验计划构建，执行仍走采购服务。确认同时检查会话version、摘要、当前绑定、当前主体/策略、引用资料版本，订单/会话完成/outbox/审计同事务。完成回放不得重复写入，结果按当前权限投影。只有归属用户可查看/补充/取消/确认，仍需统一策略授权；过期按访问时推进，不引入后台服务必需依赖。含任何新会话数据时拒绝破坏性迁移降级。


## v1.0.5 回复投递与连接运行态（已实现）

onebot_instance 1—0..1 onebot_connection；message_inbox 1—0..1 message_delivery（event_key唯一外键）。message_delivery同时关联实例、可空用户和版本化绑定快照。回复只持久化受限recipe，不持久化结果正文，终态清除recipe。连接UUID作为跨进程租约栅栏，单实例仅一个未过期拥有者。新表、状态约束、外键与队列索引通过新迁移添加，旧表与迁移不改动。完整字段、状态、权限和失败语义见[DELIVERY.md](DELIVERY.md)。


## v1.0.6 客户与销售订单

新增be0f9a8b7c6d（继承ad9e8f7a6b5c）：customer唯一编码/归属外键，sales_order客户/归属/审批人外键、唯一SO单号、非负NUMERIC总额及状态/审批人配对约束；sales_line订单/商品外键、订单内行号唯一、正数数量和非负金额。均包含UTC时间/version及FK索引。既有表、迁移、库存来源约束和策略快照不改动，不造业务资料；存在客户或销售历史时拒绝破坏性降级。完整ER关系与安全默认见SALES.md。


## v1.0.7 发货与方向流水

迁移ce1a0b9c8d7e新增sales_shipment、shipment_line、shipment_execution。销售行shipped_quantity默认0并受0≤已发≤计划约束；订单支持partially_shipped/shipped且保留审批人约束。发货/发货行/命令记录采用追加存储，PG阻止UPDATE/DELETE/TRUNCATE，SQLite阻止UPDATE/DELETE。

stock_movement新增唯一shipment_line_id外键，receipt_line_id变可空；ck_stock_movement_source要求kind与唯一业务来源配对。原正数数量检查、旧采购流水、唯一/外键/索引和不可变触发器均保留。出库历史存在时拒绝破坏性降级；无出库时可回退至be0f9a8b7c6d并保留旧采购/销售数据。SQLite重建显式保留未命名检查约束，并在事务前后检查外键。完整关系见[出库设计](SHIPMENTS.md)。

## v1.0.8 只读报表

复用库存余额、方向流水及采购/销售单据，没有新增业务表或列，因此无新迁移，迁移头保持ce1a0b9c8d7e。report/export是资源动作目录扩展，已发布策略快照不改动。授权与来源关联过滤后，在受限子查询上按仓库/商品/方向或状态/币种分组，保留NUMERIC精度，不跨币种/单位合计。
