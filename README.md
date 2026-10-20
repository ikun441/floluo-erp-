# 弗洛洛 ERP · v1.0.0 开发版

单企业、局域网、离线核心业务、模块化单体。项目正在分阶段开发，不是完整 ERP 正式版。

## 本地后端

```sh
uv sync --extra dev
uv run alembic upgrade head
uv run python -m erp.bootstrap --username admin
uv run uvicorn erp.main:app --host 127.0.0.1 --port 8000
```

先配置 DATABASE_URL（PostgreSQL）。初始化通过交互式密码输入，不通过命令行传递密码。开发测试可显式设置 SQLite URL，但不能替代 PostgreSQL 集成验证。

```sh
uv run pytest
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

测试状态、交付边界与阻塞见 [实施记录](docs/IMPLEMENTATION.md)。系统设计见 [架构](docs/ARCHITECTURE.md)、[数据库](docs/DATABASE.md)、[权限](docs/PERMISSIONS.md)。
