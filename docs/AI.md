# 可选 AI 与受控查询网关（设计，Phase 4）

AI 默认关闭；配置 base_url/model/secret reference/timeout；支持内网兼容服务。AI 只返回严格 schema Intent(operation, resource, arguments, references, confidence, parser_source)，extra=forbid，未知工具或参数拒绝。

工具注册表将 query_inventory/query_purchase_orders/query_sales_summary 等映射到受控服务；服务端注入已验证用户，不允许模型提供 user_id、role、SQL、代码或任意网络目的地。每个工具权限校验、SQL scope、字段投影、有界规模、超时与审计后，才能将结果交给模型。

状态：local_failed → consent_required → parsing → schema_validation → preview → confirm → reauthorize → execute。任何步骤失败均不自动执行。提示注入作为数据处理，AI 不访问数据库凭据/隐藏字段/内部配置。

Harness 是开发辅助工具，与产品 AI 无关。隔离网关验证见 HARNESS.md；不得将开发网关当作 ERP 的运行依赖。
