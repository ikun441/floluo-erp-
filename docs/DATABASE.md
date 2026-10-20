# 数据模型与核心关系

本文件先于业务实现建立。Phase 1 迁移只创建 identity、authorization、audit 与商品基础切片；以下业务表是后续设计，不代表已实现。

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
| stock_movement → product / warehouse / source | 有符号数量，不可变流水；冲销使用反向新流水 |
| message_binding → instance / user | 平台身份与实例复合唯一，验证挑战、撤销状态 |
| message_inbox / command_execution | 平台事件唯一键、用户幂等键、payload 摘要 |
| conversation → binding / intent | 状态、过期时间、确认摘要、版本 |
| workflow_revision / approval / approval_event | 定义快照、申请摘要、审批人与操作不可变记录 |
| outbox → aggregate | 事务内事件，发送可重试，消费端幂等 |

所有业务标识采用 UUID；金额 NUMERIC(18,2)，数量 NUMERIC(18,4)，UTC DateTime(timezone=True)。所有 FK 建立访问索引。业务行包含 created_at、updated_at、version；DB FK、唯一、CHECK 约束是第二道一致性边界。

关系示意：user ← user_role → role；gate → revision → rules(subject → resource/action/scope/fields/conditions)；user/department → product。业务扩展由 purchase_order → lines → receipts → stock_movement → balance 形成闭环。

Phase 1 审计使用 SHA256 串联，能检测链内修改，不能抵御数据库所有者重写整链或裁剪尾部。生产应由外部可信介质定期保存链头签名/锚点；应用数据库角色无 UPDATE/DELETE/TRUNCATE 权限。
