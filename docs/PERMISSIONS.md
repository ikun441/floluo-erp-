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
