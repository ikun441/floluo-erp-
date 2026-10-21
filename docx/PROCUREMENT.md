# Phase 2 采购与库存闭环（设计）

[文档导航](README.md) · [版本日志](version.md)

当前已实现分类、供应商、仓库、采购草稿与明细、提交/独立审批/取消、带版本和幂等键的分批入库、库存/流水/收货查询、明确业务规则配置以及相应Web页面。当前不支持通用工作流、退货、冲销、含税与汇率换算。

## 数据与依赖（先于业务代码建立）
category → product；supplier → purchase_order → purchase_line → purchase_receipt → receipt_line → stock_movement。
warehouse + product → inventory_balance（复合唯一）。
command_execution 以 subject + idempotency key 唯一约束防重复；业务数据、命令记录、流水、余额、审计、outbox 同事务提交。

金额 NUMERIC(18,2)，数量 NUMERIC(18,4)。不使用浮点数，不静默四舍五入：超过精度或行金额不能精确到分则拒绝。订单显式填写币种，提交、审批和新入库前必须在系统配置中确认支持币种与无税模式。税率、多币种换算尚未实现。

状态：draft → submitted → approved → partially_received → received。draft 可编辑；无收货前可取消；完成收货只能后续通过冲销流程调整，当前不提供物理删除、退货和超收。
默认需要另一位有审批权限的人员批准，禁止自审批。管理员可以显式配置该规则；无配置时采用安全默认值。

创建和每次状态变更都从服务端身份解析所有者/部门；引用的商品、供应商、仓库必须当前可读。读取关联数据再次检查其权限，隐藏成本同时隐藏单价、行金额、总额，不能通过嵌套对象绕过字段约束。

入库要求订单receive、仓库receive、收货单create权限。事务先锁authorization_gate，再锁订单、明细和余额；按稳定ID顺序锁定。收货数量不能超过剩余数量，库存只通过不可变流水改变。幂等重试重新授权并重新投影，不能返回过期权限下的缓存响应。

## 接口
/api/v1/categories、suppliers、warehouses：受保护资料维护。
/purchase_orders：草稿创建、列表、详情、草稿修改。
/purchase_orders/{id}/submit、approve、cancel：显式状态转换。
/purchase_orders/{id}/receive：带Idempotency-Key和订单版本的入库命令。
/purchase_receipts、inventory_balances、stock_movements：只读受限查询。
/system_configuration：已授权管理员显式配置业务规则；新增模块不自动扩大现有策略权限。

已成功收货的重放仅回读当前授权下的回执，不执行新入库；业务配置停用不会删除或重写历史流水。
