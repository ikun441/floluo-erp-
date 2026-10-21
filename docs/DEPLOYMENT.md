# 部署与恢复

## 当前 Compose 基础

Linux / Docker Compose：Nginx → Next.js / FastAPI → PostgreSQL 持久化卷。只暴露 Nginx；数据库和后端没有宿主端口映射。migrate 服务成功完成后启动后端，再经健康检查启动前端。管理员通过独立交互式 CLI 初始化，服务启动不自动创建管理员或业务数据。

运行 `python3 scripts/init_env.py` 生成权限0600的本机 .env；数据库密码随机生成，不回显，不覆盖已有配置。默认仅127.0.0.1:8080、HTTP与非Secure Cookie，用于本机验证。局域网正式使用必须配置 TLS 终止、APP_ORIGIN、SECURE_COOKIES=true 和适当的绑定地址；当前 Nginx 示例尚未包含证书管理。

后端及前端容器使用非root账号。数据库初始化用户当前也是schema所有者，因此尚未满足生产最小权限角色隔离。生产上线前需拆分迁移所有者与应用角色，演练最小权限、恢复与外部审计锚定。

Redis、Celery 和 outbox 在需要后台任务时随对应模块加入，Phase 1 核心不依赖它们。构建阶段需要下载依赖，构建后的核心运行不需要第三方云服务。

## 备份与恢复

使用 pg_dump --format=custom 备份。恢复前停止写入并保存当前备份，在独立数据库中使用 pg_restore 验证，核对 Alembic 版本、行数与审计链；库存模块加入后还必须核对流水和余额。不得未经确认覆盖生产数据库。密钥、附件和配置另行加密备份，定期实际恢复演练。

## 本机验证范围

本机无 Docker，未执行 docker compose build/up 或备份恢复演练。已通过项目内真实 PostgreSQL 18.4 的迁移、认证、权限、审计和并发测试；这不能替代 Compose 中 PostgreSQL 17 的镜像启动与部署验证。

## 采购资料基础迁移

5a6ef43a4a48为新增迁移，不修改前两份迁移。请先备份并在数据库副本验证升级，再执行alembic upgrade head。迁移不改变旧策略权限；管理员在权限中心明确授权categories、suppliers、warehouses及products.category_id。配置表的币种为空、税模式未配置、独立审批人为true；目前已开放采购业务，使用前需明确授权与配置。

迁移降级只允许新业务表为空且没有v2审计事件的数据库；运行新应用后通常会产生v2审计，因此不能把downgrade当成通用业务回滚。代码回滚和恢复数据库应使用经过验证的一致性备份方案，恢复演练尚未完成。本变更不声称支持在线无停机迁移。

采购MVP服务现已开放，但已有策略不会自动获得新权限。管理员需在权限中心明确配置采购资源、warehouses.receive及采购金额字段组，再进入“采购业务规则”明确支持币种与无税模式。默认保留独立审批人，由另一个有approve权限的账号审批；不自动关闭该限制。退货、冲销、含税和汇率换算尚不支持。outbox尚无通知消费者，采购成功不代表外部通知已发送。

## v1.0.3 消息实例迁移与网络

新增8b7a6c5d4e3f，不修改已发布迁移。升级前备份；新表为空时可降级，存在实例、挑战、绑定或去重记录时拒绝破坏性降级。已有策略需在Web权限中心显式增加消息资源授权。

OneBot客户端使用反向Universal连接 `wss://<ERP地址>/onebot/v11/ws/<实例ID>`，按ONEBOT.md配置Bearer和bot标识。Nginx示例包含WebSocket Upgrade转发；后端新增websockets运行依赖，容器限制帧大小为65536。令牌通过已授权Web创建/轮换生成，不写入Compose或仓库。客户端负责断线重连；当前ERP不主动拨号OneBot。

本地真实TCP与ASGI测试不能代替真实OneBot客户端、生产Nginx/TLS或Docker镜像验收。收件箱/挑战默认保留，暂无清理后台；需规划容量，清理去重记录会改变重放保证。

## v1.0.4 会话迁移

新增9c8b7a6d5e4f，在原消息身份迁移之后创建操作会话。先备份并在副本验收后执行alembic upgrade head；存在会话时拒绝破坏性降级。没有新增外部服务或环境密钥依赖。旧角色需显式授权message_operations，详见OPERATIONS.md。

会话过期由访问时检查推进，不依赖Celery/Redis；保留历史以支持重放与审计，目前没有自动清理后台。版本更新日志主文件为docx/version.md，保留文件名与Markdown格式。


## v1.0.5 升级与恢复

备份后先停止旧后端，再执行`alembic upgrade head`（新增ad9e8f7a6b5c），最后启动新版本；禁止混跑旧版无租约发送器与新版发送器。已有收件箱不补发，新历史存在时迁移拒绝破坏性降级。旧角色需在权限中心显式添加onebot_connections/message_deliveries.read及所需字段/数据范围；不自动扩大权限。

不增加Redis/Celery依赖，当前Universal连接负责有界发送轮询。正常断线释放租约；异常退出后最多等待90秒失效，再由OneBot客户端重连接续未过期任务。最多3次、5分钟，失败/过期在监控查看，不提供绕权强制补发。真实QQ、多进程与Linux容器生产部署仍待验收，保留/备份/清理策略需另行落实。
