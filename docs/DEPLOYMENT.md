# 部署与恢复

目标 Linux Docker Compose：nginx → frontend/backend；PostgreSQL 数据卷；Redis 与 Celery 按后续任务模块启用。镜像构建/依赖下载需要网络，构建后核心运行不需要云服务。

.env 由 .env.example 复制并生成随机数据库密码；没有默认管理员密码。启动迁移由单独 migrate 服务完成，bootstrap 是单独交互式 CLI，服务启动不会自动造管理员或演示数据。

备份：pg_dump --format=custom；恢复前停写、保存当前备份，在独立数据库运行 pg_restore 并核对迁移版本、行数、库存流水与审计链。禁止未确认覆盖生产数据库。密钥、上传附件、配置另行加密备份。

本机没有 Docker/PostgreSQL 可执行文件，因此 Compose 与 PostgreSQL 并发验证若未另行记录，均属于待执行。
