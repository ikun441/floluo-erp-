# 统一权限引擎

[文档导航](README.md) · [版本日志](version.md)

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

## v1.0.4 确认请求

message_operations是独立注册资源，支持read/create/update/cancel/confirm、own范围。旧策略不自动增加权限。服务端始终限定当前owner；平台请求额外限定原binding ID/version，平台身份不能提供ERP主体。

preview字段控制参数写入与完整预览展示，state字段控制显式取消/确认。展示预览前重查业务create/read和引用范围；完整关键金额不可读时拒绝预览。刷新导致version变化后再次决策，避免旧读权限继续展示。业务result/result_id只在当前采购读取范围及字段投影允许时返回，列表不直接暴露result_id。created_at/expires_at/preview/result等虚拟字段不能用作SQL条件AST。

确认检查原参数摘要和资料版本并在创建后提交前复核；重放再次要求当前create权限并投影当前可见结果。requires_approval仍拒绝执行，不把请求确认当作通用审批。


## v1.0.5 监控与投递

onebot_connections与message_deliveries仅有read；后者支持own/records/all，前者支持records/all。关联onebot_instances.id必须在当前可读范围，筛选state和游标id也需可读。监控不注册recipe、收件人、连接UUID/回执token或原文字段，不能经通用CRUD读写。旧角色必须显式增加新资源权限；前端隐藏不替代后端约束。

投递器是内部受限执行者，不能接受客户端角色/SQL/自由工具。业务回复每次按保存主体、平台收件人和绑定版本重建Engine，检查bindings.use后调用相同业务服务。只重建查询或已有请求视图，不重放创建/审批/入库。身份失效或请求授权不足抑制并清除recipe，读取权限变化按当前范围/字段重新过滤。


## v1.0.6 销售资源

customers复用目录read/create/update；sales_orders注册read/create/update/submit/approve/cancel，支持own/department/departments/records/all。只在新bootstrap显式生成策略，已发布快照不改动，升级需管理员在权限中心显式授予。sales_orders字段为订单ID/版本/单号/customer_id/owner_id/department_id/currency/total/status/note/approved_by/lines/unit_price/line_amount；后三者为虚拟字段，禁止SQL条件。

销售列表/详情在SQL中过滤当前客户和所有商品的可读ID，状态/游标探测须相应字段可读；金额三字段取最严格投影，不能从明细反推隐藏总额。编辑旧/新候选与实际提交字段均校验；状态迁移旧/新状态授权，requires_approval继续拒绝，独立审批不替代业务权限。创建归属取服务端当前身份。审批不产生库存权限或变动。


## v1.0.7 出库授权矩阵

| 资源/字段 | 必需授权或用途 |
| --- | --- |
| sales_orders.ship | 发货前/后订单状态均授权，显式拒绝优先 |
| warehouses.ship | 当前目标仓库有出库操作权限，且仓库ID可读 |
| sales_shipments.create | 发货资源符合范围，order_id/warehouse_id/lines可写 |
| inventory_balances.read | 目标库存当前id和quantity可读，否则统一404 |
| customers/products.read | 客户及订单全部商品ID当前可读，本次发货引用须启用 |
| sales_shipments.read | 查询/回放发货记录；范围与来源关系在分页前过滤 |
| sales_orders.shipped_quantity | 新增虚拟字段，控制各行已发数量；不允许SQL条件 |

旧策略快照不变，不自动增加ship动作、发货资源或已发字段。发货读取不返回订单金额；发货与库存流水的来源ID须当前可读，隐藏来源ID不能通过游标或关联绕过。回放重新校验当前ship/create和读取授权，不能取队列里的旧数据或重复执行扣减。库存余额/流水仍无通用写入接口。

## v1.0.8 统计与导出

inventory_balances、stock_movements、purchase_orders、sales_orders新增report/export动作，旧策略不自动扩权。统计=read∩report，导出=read∩report∩export，各动作的范围、条件、显式拒绝、待审批和字段最严约束均在SQL聚合前应用。Engine.field_scope泛化原可读字段SQL过滤，readable_scope保持原契约。

库存要求warehouse_id/product_id/quantity，流水另需kind；关联商品id/sku/name/unit、仓库id/code/name必须完整可读。订单数量要求status/currency，金额要求三项total/unit_price/line_amount均完整可读；否则该行不参与对应指标，不返回排除行数。所有筛选/分组字段在授权后使用。既有来源单据关系约束继续生效。详见[配置与统计口径](REPORTS.md)。
