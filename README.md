# 弗洛洛 ERP · v1.0.3 开发版

<img src="frontend/public/brand/floluo-logo.png" alt="弗洛洛 ERP Logo" width="144" height="144">

面向单一企业的局域网 ERP，采用模块化单体、离线核心业务和统一权限边界。当前已建立架构设计、Phase 1基础及Phase 2采购MVP闭环，尚非完整 ERP 正式版。

已实现：真实登录与服务端会话、多角色用户和组织管理、默认拒绝的权限引擎、数据范围与字段约束、策略版本发布与模拟、审计链、商品及分类、供应商、仓库基础资料，以及连接真实 API 的 Next.js 管理界面。登录页包含本地生成的 Three.js 3D 场景与 Motion 动效。

采购已支持草稿、独立审批、分批入库及库存流水。OneBot 已支持反向 Universal WebSocket、密码复核的单次账号绑定、持久化去重，以及复用权限引擎的采购/库存私聊查询。消息写入、确认会话、正向 WebSocket 和 AI 尚未实现。通用审批工作流、销售报表也尚未实现；不提供伪成功接口或演示订单。项目 Logo 使用用户提供的 Q 版原图，详见 [品牌资源](docs/BRANDING.md)。

首次使用采购前，需由已授权管理员在Web明确配置支持币种和税模式；默认未配置时拒绝提交。审批人默认必须与创建人不同。

## Docker Compose

需要 Docker Compose。默认配置仅绑定本机，尚未在本开发机进行容器启动验证。

```sh
python3 scripts/init_env.py
docker compose up --build -d
docker compose exec backend python -m erp.bootstrap --username admin
```

初始化脚本生成随机数据库密码，已有 .env 不覆盖。管理员密码通过终端交互输入，至少14字符，无默认账号密码。访问 http://127.0.0.1:8080 。局域网部署前配置 TLS、准确的 APP_ORIGIN 与 Secure Cookie，参见 [部署文档](docs/DEPLOYMENT.md)。

## 本地开发

Python 3.12+（本机实际使用3.13），Node.js 24+，PostgreSQL。

```sh
uv sync --frozen --extra dev
```

创建仅本机可读的 .env，设置 DATABASE_URL、APP_ORIGIN=http://127.0.0.1:3000；仅本机 HTTP 开发可设置 SECURE_COOKIES=false。然后：

```sh
uv run alembic upgrade head
uv run python -m erp.bootstrap --username admin
uv run uvicorn erp.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

另开终端：

```sh
cd frontend
npm ci
npm run build
npm start
```

前端默认连接 http://127.0.0.1:8000 。AI 和消息服务不参与这些启动步骤。

## 验证

```sh
uv run pytest -q
uv run ruff check backend tests scripts
uv run ruff format --check backend tests scripts
cd frontend
npm run typecheck
npm run format:check
npm run build
```

真实 PostgreSQL 测试采用项目内独立临时集群，不安装系统服务：

```sh
cd scripts/testing
npm ci
npm run postgres
```

若 npm 提示阻止 @embedded-postgres 平台包 postinstall，先审查其 hydrate-symlinks.js，再按 npm 提示批准该包初始化；本机已审查并执行 darwin-arm64 包的库链接恢复。该测试工具参考 [embedded-postgres](https://github.com/leinelissen/embedded-postgres)，与生产部署无关。

浏览器测试会自行启动独立临时数据库与本机后端；请先构建前端，并确保3000/8000端口空闲：

```sh
cd scripts/testing
npx playwright install chromium
npm run e2e
```

测试专用固定口令仅存在于独立的回环测试数据库，生产 bootstrap 不使用它。运行目录和浏览器产物位于忽略提交的 .test-runtime/ 与 output/。

## 项目说明

- [架构](docs/ARCHITECTURE.md) · [数据库](docs/DATABASE.md) · [权限模型](docs/PERMISSIONS.md)
- [采购设计与当前范围](docs/PROCUREMENT.md) · [API](docs/API.md) · [OneBot](docs/ONEBOT.md) · [AI](docs/AI.md) · [安全](docs/SECURITY.md)
- [登录设计](docs/LOGIN_DESIGN.md) · [Harness](docs/HARNESS.md) · [实施与验证记录](docs/IMPLEMENTATION.md)
