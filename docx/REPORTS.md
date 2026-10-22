# 库存分析与基础报表

[文档导航](README.md) · [版本日志](version.md)

## 本阶段设计

报表是模块化单体内的只读应用服务，Web → reports_api → reports → 现有权限引擎/业务查询 → PostgreSQL；没有独立数据副本、AI依赖或新业务表。本阶段不改变数据库结构，不需要新迁移。

同一Gate事务内读取当前策略。inventory、movements、purchases、sales四类报表，分别绑定inventory_balances、stock_movements、purchase_orders、sales_orders。报表要求read与report交集；CSV另要求export交集。每个动作的显式拒绝、条件、范围、字段最严约束和待审批限制均在聚合前应用。旧角色不会自动获得新增动作。

库存按仓库/商品展示当前实际余额，流水按仓库/商品/方向汇总实际发生数量；采购与销售按状态/币种汇总订单数，可显式选择金额指标。金额要求total、unit_price、line_amount均可读。不计算利润、成本、预警阈值或汇率。不同商品/单位和币种不合计。订单金额不是现金流或收入确认。

所有报表沿用业务查询中的商品、仓库、客户/供应商和来源单据可见性，关联维度展示前额外检查字段。隐藏/脱敏字段的行不参与相应报表，不返回被排除行数。筛选只作用于完整可读的维度。零结果既可能是无记录，也可能是当前授权范围没有合格记录。

每次最多10000条合格来源记录、200组；超限整体拒绝，要求缩小筛选，不返回部分汇总。数据库计算聚合，不加载完整业务对象或逐行查询。PostgreSQL报表SQL使用5秒statement_timeout；SQLite开发环境使用临时progress handler约束查询时间。CSV只导出当前筛选下完整合格汇总，防公式注入，记录种类、指标、行数与策略版本等元数据，不记录业务金额或下载内容。

## API约定

GET /api/v1/reports/{inventory|movements|purchases|sales}

GET /api/v1/reports/{inventory|movements|purchases|sales}/export

查询参数：metric=count|amount（只适用于订单，默认count）；warehouse_id/product_id（库存/流水），status/currency（订单），kind（流水）。参数白名单与长度校验，错误类别统一422；当前版本不提供日期维度，避免未授权时间字段旁路。

返回items为完整合格分组，source_rows仅为合格来源条数，policy_revision为当前策略号。字段或条件变化后不复用旧结果。前端按报表及已应用筛选建立查询键，查询错误时不展示旧数据，导出每次重新授权。
