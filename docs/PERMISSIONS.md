# 统一权限引擎

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

## v1.0.3 消息资源

新增 onebot_instances（read/create/update/rotate_token）与 message_bindings（read/create/revoke/use，自身范围）。access_token 与 password 均为只写字段，策略拒绝 read/masked 模式，通用投影也永不返回这些字段。实例令牌创建/轮换仅在已获得明确令牌写权限的响应中返回一次。

实例连接认证与 ERP 绑定身份不同：可信协议源提供平台身份，单次挑战将其映射到 ERP 当前用户；每条业务查询重新构建 Subject 和策略引擎。消息查询复用采购/库存 SQL 范围与字段投影，用户无法提供角色/部门替代服务端主体。群聊不返回业务结果。升级不修改既有策略，新资源仍默认拒绝。

修正 requires_approval 的读取路径：SQL 列表范围排除任何匹配的待审批允许策略，详情投影同样拒绝；Web 与消息一致。在通用审批回执机制完成前，这类读取不返回记录。
