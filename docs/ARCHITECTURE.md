# 技术架构（Phase 0）

## 部署与模块边界

Linux / Nginx → Next.js Web、FastAPI REST / WebSocket → 统一应用服务 → 权限决策 + 业务领域 → SQLAlchemy / PostgreSQL。
Celery + Redis 规划用于通知、AI 超时任务、报表任务，当前核心启动无此必需依赖；事务 outbox 发布已提交事件，业务正确性不依赖队列在线。
Redis 不作为库存或授权真相来源。AI 与消息协议可独立关闭，核心 Web 不依赖外网。

模块依赖：identity → authorization → catalog → procurement → inventory；sales 依赖 catalog/inventory；workflow 通过应用命令触发并重新授权；audit 为基础设施横切能力。adapters(onebot/web/ai_tools) 仅调用 application，不反向依赖 adapter。

## 一致性

Phase 1 采用数据库 authorization_gate 单行锁，事务入口获取后加载用户、角色、当前策略与资源并完成操作、审计和提交。此保守实现串行化请求，优先保证撤权与写入的严格顺序，后续在 PostgreSQL 并发测试支持下细化为共享授权锁 + 资源行锁。
库存现已使用 warehouse/product balance 行锁、不可变流水、业务来源唯一键、幂等键和 outbox 同事务提交。异步任务执行前重新授权，不沿用排队时的允许结果。

## 状态机

采购：draft → submitted → approved → partially_received → received；draft/submitted/approved可在未入库时取消；通用撤回与冲销尚未实现。具体退货、超收和金额规则待确认，未配置时拒绝。
审批：pending → approved/rejected/withdrawn/expired。审批通过只授权重新提交相同摘要的命令，不自动扩大申请人权限。

## 安全与运行

服务端会话，Argon2 密码，Cookie HttpOnly/Secure/SameSite，修改请求 CSRF，来源校验。策略版本与用户状态由数据库实时读取。日志使用 trace id，严禁密码、AI 密钥、消息原文默认落日志。
采用显式资源注册表和条件 AST，禁止运行时任意 Python/SQL 插件。模块注册包含资源字段、允许动作、服务入口和命令 schema。

## 技术依据

FastAPI 密码哈希参考 https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ ；SQLAlchemy 并发版本参考 https://docs.sqlalchemy.org/en/20/orm/versioning.html 。服务端会话用于可即时撤销认证，避免把角色写入长期令牌。

## Phase 2落地

procurement_api仅适配请求/响应，procurement服务统一执行草稿、提交、审批、取消、入库；复用当前事务、身份和权限引擎。每次请求先锁authorization_gate，订单/行/余额再按稳定顺序锁定。收货、收货行、不可变流水、余额、幂等记录、订单状态、outbox及成功审计同事务提交；失败先回滚，再独立追加失败审计。意外异常同样尝试记录500；若数据库本身不可用，仅输出无参数的追踪日志，不能保证数据库审计落盘。

当前库存服务只支持采购入库，尚不实现销售出库、退货、成本核算或冲销。outbox是持久化待处理记录，未连接消息消费者，不返回虚构通知成功。系统无需Redis/AI/OneBot即可完成当前Web采购流程。

## v1.0.3 消息切片

OneBot transport → message_gateway（Gate、事务、收件箱和审计）→ message_service（绑定/受控查询）→ 已有采购范围与投影/权限引擎。适配器不读写数据库、不解释ERP角色。Web messaging_api调用相同身份服务和统一权限资源。当前只实现反向Universal与私聊只读工具，AI和消息写入不参与核心启动。

## v1.0.4 预览与执行分离

Web/OneBot → message_operations应用服务 → procurement.prepare_draft纯计划/统一权限 → Web密码复核后procurement.draft。预览与执行共用校验逻辑，参数及引用版本摘要将用户所见与提交内容绑定；版本或绑定变化后重新预览。MessageOperation持久化收集/确认/取消/过期/完成状态，消息适配器不直接写业务数据。新增操作工作台连接真实API；版本日志迁至docx/version.md。


## v1.0.6 客户与销售基础

SalesView → sales_api → sales → order_support + Engine → sales_models/PostgreSQL。客户资料使用同一受限目录服务，权限字段/动作通过注册表驱动权限中心。order_support仅提取原有受限引用、配置、版本、线格式及outbox工具；procurement保留导入兼容，不改变其调用契约。销售和采购共享币种/税配置，销售始终独立审批；销售订单只进入草稿/提交/批准/取消状态，本切片不变动库存。未来出库复用库存领域事务，不直接改余额。详见SALES.md。
