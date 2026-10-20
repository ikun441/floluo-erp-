# 安全边界

Argon2id 密码、随机服务端会话、token/CSRF 仅存摘要、即时用户禁用与会话撤销。失败登录按来源限流并按账号锁定，所有入口通用。
Cookie 默认 Secure/HttpOnly/SameSite=strict；局域网生产部署 TLS。开发模式显式关闭 Secure 时仅供本机。禁止通配 CORS，写请求校验 Origin 和 CSRF。

权限引擎为最终边界，管理员角色名称无特殊逻辑。策略中不能出现代码。审计追加哈希链与 PostgreSQL 禁止修改触发器；数据库所有者不在防篡改保证范围内，需离机锚定。错误审计只记录路由、状态、trace，不记录输入密码和 token。

API Key 不提交、不回显；通过服务器环境/受限 secret 文件配置。AI 默认关闭。外网发布、正式 release、破坏性恢复需显式操作授权。

上线前必须完成 PostgreSQL 并发、TLS、备份恢复演练与应用角色最小权限验证；本开发阶段不宣称已达成生产安全认证。
