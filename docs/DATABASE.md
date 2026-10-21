# 数据模型与核心关系

本文件先于业务实现建立。Phase 1 迁移只创建 identity、authorization、audit 与商品基础切片；Phase 2已迁移采购/库存基础表，并已开放采购单、审批、入库和库存的真实接口。消息和工作流表仍为后续设计。

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
| stock_movement → product / warehouse / source | 当前仅正数采购入库模型；出库/冲销将使用后续迁移扩展 |
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
