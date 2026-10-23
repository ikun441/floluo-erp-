# 弗洛洛 ERP · v1.0.9 开发版

<img src="frontend/public/brand/floluo-logo.png" alt="弗洛洛 ERP Logo" width="144" height="144">

面向单一企业局域网的 ERP，采用模块化单体、离线核心业务和统一权限边界。当前为 **v1.0.9 开发版**，已接入真实数据库与业务 API。

[文档导航](docx/README.md) · [版本日志](docx/version.md) · [当前进度与验收范围](docx/IMPLEMENTATION.md) · [部署说明](docx/DEPLOYMENT.md)

| 模块           | 当前能力                                                               |
| -------------- | ---------------------------------------------------------------------- |
| 身份与权限     | 登录、会话、组织、多角色、数据范围、字段约束、条件规则、策略模拟与审计 |
| 基础资料       | 商品、分类、供应商、客户、仓库的受权限控制管理                         |
| 采购与库存     | 草稿、独立审批、分批入库、库存余额与流水                               |
| 客户与销售     | 多行草稿、独立审批、分批出库、发货记录、库存不足保护与幂等重试         |
| 消息与离线交互 | OneBot 反向连接、绑定、去重、离线解析、采购请求确认、回复与连接监控    |
| 分析与报表     | 库存/出入库、采购/销售汇总、字段保护与独立授权 CSV 导出                |
| 可选 AI        | 显式同意、结构化预览、受控库存/采购/销售汇总查询、默认关闭             |
| Web 管理       | 登录 3D 动效、业务表单、权限中心及桌面/手机布局                        |

首次提交采购或销售审批前，管理员需在「业务规则配置」明确币种和税模式。已有安装需显式授权新增资源；销售创建人始终不能自批。审批不预留库存，实际出库按当前数量扣减；退货/冲销、AI 写入、多轮补充、消息平台 AI 与通用审批仍在后续计划中，具体边界见 [销售说明](docx/SALES.md)、[销售出库](docx/SHIPMENTS.md)、[报表说明](docx/REPORTS.md) 和 [实施记录](docx/IMPLEMENTATION.md)。

项目 Logo 使用用户提供的 Q 版原图，详见 [品牌资源](docx/BRANDING.md)。

## Docker Compose

需要 Docker Compose。默认配置仅绑定本机，尚未在本开发机进行容器启动验证。

```sh
python3 scripts/init_env.py
docker compose up --build -d
docker compose exec backend python -m erp.bootstrap --username admin
```

初始化脚本生成随机数据库密码，已有 .env 不覆盖。管理员密码通过终端交互输入，至少14字符，无默认账号密码。访问 http://127.0.0.1:8080 。局域网部署前配置 TLS、准确的 APP_ORIGIN 与 Secure Cookie，参见 [部署文档](docx/DEPLOYMENT.md)。

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

## 文档入口

所有设计、业务、运维和开发文档统一放在 **[docx/](docx/README.md)**。

| 想了解的内容               | 从这里开始                                                       |
| -------------------------- | ---------------------------------------------------------------- |
| 部署、升级与恢复           | [部署说明](docx/DEPLOYMENT.md)                                   |
| 已实现功能、验证与后续目标 | [实施记录](docx/IMPLEMENTATION.md) · [版本日志](docx/version.md) |
| 采购、销售、消息等业务流程 | [业务文档导航](docx/README.md#business)                          |
| 架构、数据库、API 与安全   | [开发文档导航](docx/README.md#development)                       |
| 后续会话的开发规范         | [AGENTS.md](AGENTS.md)                                           |
