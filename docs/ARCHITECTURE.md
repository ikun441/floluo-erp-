# 技术架构（Phase 0）

## 部署与模块边界

Linux / Nginx → Next.js Web、FastAPI REST / WebSocket → 统一应用服务 → 权限决策 + 业务领域 → SQLAlchemy / PostgreSQL。
Celery + Redis 用于通知、AI 超时任务、报表任务；事务 outbox 发布已提交事件，业务正确性不依赖队列在线。
Redis 不作为库存或授权真相来源。AI 与消息协议可独立关闭，核心 Web 不依赖外网。

模块依赖：identity → authorization → catalog → procurement → inventory；sales 依赖 catalog/inventory；workflow 通过应用命令触发并重新授权；audit 为基础设施横切能力。adapters(onebot/web/ai_tools) 仅调用 application，不反向依赖 adapter。

## 一致性

Phase 1 采用数据库 authorization_gate 单行锁，事务入口获取后加载用户、角色、当前策略与资源并完成操作、审计和提交。此保守实现串行化请求，优先保证撤权与写入的严格顺序，后续在 PostgreSQL 并发测试支持下细化为共享授权锁 + 资源行锁。
库存后续使用 warehouse/product balance 行锁、不可变流水、业务来源唯一键、幂等键和 outbox 同事务提交。异步任务执行前重新授权，不沿用排队时的允许结果。

## 状态机

采购：draft → submitted → approved → partially_received → received；draft 可取消，submitted 可撤回，完成入库后只能以冲销单调整。具体退货、超收和金额规则待确认，未配置时拒绝。
审批：pending → approved/rejected/withdrawn/expired。审批通过只授权重新提交相同摘要的命令，不自动扩大申请人权限。

## 安全与运行

服务端会话，Argon2 密码，Cookie HttpOnly/Secure/SameSite，修改请求 CSRF，来源校验。策略版本与用户状态由数据库实时读取。日志使用 trace id，严禁密码、AI 密钥、消息原文默认落日志。
采用显式资源注册表和条件 AST，禁止运行时任意 Python/SQL 插件。模块注册包含资源字段、允许动作、服务入口和命令 schema。

## 技术依据

FastAPI 密码哈希参考 https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/ ；SQLAlchemy 并发版本参考 https://docs.sqlalchemy.org/en/20/orm/versioning.html 。服务端会话用于可即时撤销认证，避免把角色写入长期令牌。
