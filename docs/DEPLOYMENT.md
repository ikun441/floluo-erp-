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
