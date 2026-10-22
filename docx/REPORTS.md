# 库存分析与基础报表

[文档导航](README.md) · [版本日志](version.md)

## 已实现的范围

报表是模块化单体内的只读应用服务，Web → reports_api → reports → 现有权限引擎/业务查询 → PostgreSQL；没有独立数据副本、AI依赖或新业务表。本阶段不改变数据库结构，不需要新迁移。

同一Gate事务内读取当前策略。inventory、movements、purchases、sales四类报表，分别绑定inventory_balances、stock_movements、purchase_orders、sales_orders。报表要求read与report交集；CSV另要求export交集。每个动作的显式拒绝、条件、范围、字段最严约束和待审批限制均在聚合前应用。旧角色不会自动获得新增动作。

库存按仓库/商品展示当前实际余额，流水按仓库/商品/方向汇总实际发生数量；采购与销售按状态/币种汇总订单数，可显式选择金额指标。金额要求total、unit_price、line_amount均可读。不计算利润、成本、预警阈值或汇率。不同商品/单位和币种不合计。订单金额不是现金流或收入确认。

所有报表沿用业务查询中的商品、仓库、客户/供应商和来源单据可见性，关联维度展示前额外检查字段。隐藏/脱敏字段的行不参与相应报表，不返回被排除行数。筛选只作用于完整可读的维度。零结果既可能是无记录，也可能是当前授权范围没有合格记录。

每次最多10000条合格来源记录、200组；超限整体拒绝，要求缩小筛选，不返回部分汇总。数据库计算聚合，不加载完整业务对象或逐行查询。PostgreSQL报表每条SQL使用5秒statement_timeout；SQLite开发环境使用临时progress handler约束查询时间。CSV只导出当前筛选下完整合格汇总，防公式注入，记录种类、指标、行数与策略版本等元数据，不记录业务金额或下载内容。

## API约定

GET /api/v1/reports/{inventory|movements|purchases|sales}

GET /api/v1/reports/{inventory|movements|purchases|sales}/export

查询参数：metric=count|amount（只适用于订单，默认count）；warehouse_id/product_id（库存/流水），status/currency（订单），kind（流水）。参数白名单与长度校验，错误类别统一422；当前版本不提供日期维度，避免未授权时间字段旁路。

返回items为完整合格分组，source_rows仅为合格来源条数，policy_revision为当前策略号。字段或条件变化后不复用旧结果。前端按报表及已应用筛选建立查询键，查询错误时不展示旧数据，导出每次重新授权。

## 报表与授权对照

| 页面       | 主资源             | 分组                   | 指标                     |
| ---------- | ------------------ | ---------------------- | ------------------------ |
| 当前库存   | inventory_balances | 仓库、商品及原单位     | 实际余额                 |
| 出入库汇总 | stock_movements    | 仓库、商品、单位、kind | 正数发生量，方向分别展示 |
| 采购汇总   | purchase_orders    | status、currency       | 订单数，或订单数与金额   |
| 销售汇总   | sales_orders       | status、currency       | 订单数，或订单数与金额   |

| 参数                      | 适用报表   | 取值                              |
| ------------------------- | ---------- | --------------------------------- |
| warehouse_id / product_id | 库存、流水 | 完整可读ID，最多80字符            |
| kind                      | 流水       | purchase_receipt / sales_shipment |
| status                    | 订单       | 对应采购或销售的合法业务状态      |
| currency                  | 订单       | 三位大写ASCII币种代码             |
| metric                    | 订单       | count（默认）/ amount             |

参数不能跨报表使用。未知参数、非法状态/币种和非订单的amount指标返回422。当前没有日期筛选与趋势报表。

## 管理员授权顺序

1. 在「权限中心」选择用户或角色，先配置主资源read及业务引用的读取范围。
2. 显式增加主资源report，配置相同或更小的数据范围；需要下载时再配置export。read不自动包含report，report不自动包含export。
3. 为每个动作配置本报表所需字段：库存需要warehouse_id/product_id/quantity，流水另需kind；订单数量需要status/currency，金额另需total/unit_price/line_amount。
4. 库存维度还需商品id/sku/name/unit和仓库id/code/name可读；业务订单与流水保留原有来源单据、客户/供应商与全部商品约束。
5. 使用模拟器检查单个记录的report/export决策，再使用目标账号检查完整报表。模拟器不替代关联和分组约束。

未授予某动作的可执行允许规则时返回403；存在规则但当前范围内全部被拒绝、待审批或字段不完整时，返回零条合格记录，CSV只有表头。前端不会显示被排除的行数。页面表格在重新校验或请求失败期间隐藏旧结果；导出不复用表格旧缓存。

## 导出与运行边界

CSV为UTF-8 BOM，固定列名，保留十进制文本精度。文本单元格以=、+、-、@或危险空白前缀开头时加单引号，避免电子表格解释为公式。文件名固定为报表类型，不包含用户输入。

超出来源/分组上限返回422（report_source_limit/report_group_limit）；数据库超时返回503（report_query_timeout），事务回滚后记录失败审计。PostgreSQL超时约束为每条SQL5秒，SQLite临时progress handler覆盖报表查询。报表仍使用全局Gate，规模上限不代表生产性能已验收。本版没有库存成本、利润、现金流、BI、异步导出或AI查询能力。
