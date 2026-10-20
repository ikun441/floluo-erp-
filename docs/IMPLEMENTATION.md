# 实施与验证记录

版本1.0.0为当前开发版本，未创建正式 release。

## 当前成果

Phase 0：已建立架构、模块依赖、核心数据关系、权限模型、消息与AI状态机、API规范和AGENTS。

Phase 1可运行基础切片：真实认证与可撤销会话；用户、部门、岗位、多角色管理；数据驱动RBAC/ABAC策略、SQL范围过滤、字段投影/脱敏/写入限制、创建与修改前后状态校验；不可变策略版本、保守冲突提示与模拟器；追加审计链与数据库防修改触发器；真实商品基础资料；Next.js管理界面与3D登录入口。

这不是完整Phase 1或完整ERP交付。授权与审计采用全局事务锁串行化请求，尚需性能优化；审计尚未记录完整变更前后摘要；历史策略浏览/恢复UI、组织管理体验、系统配置和生产部署验收仍需完善。

## 已实际运行

2026-10-20：
- 后端首次SQLite测试18项通过。
- 增加真实PostgreSQL后，首次运行发现审计时间文本随会话时区变化，两项失败；已改为UTC固定微秒格式。
- 修复后：38 passed，2 skipped。包含SQLite的18项、PostgreSQL的18项及PostgreSQL的两项并发测试；跳过的是SQLite无法提供的两项真实行锁测试。
- PostgreSQL测试覆盖迁移、审计链验证、防修改、并发版本冲突、撤权先于等待写入生效。
- 测试运行器显式传递pytest退出码，避免第三方退出钩子掩盖失败。
- 后端Ruff检查、格式检查通过；前端TypeScript、格式检查与生产构建已通过。
- 真实桌面浏览器确认WebGL已渲染、无横向溢出、暂停按钮有效；实际登录进入工作台。发现并修复登录后Query缓存未刷新的问题。
- Playwright自动化4项全部通过（16.5秒）：真实登录/登出、部门写入并刷新验证、权限矩阵加载；真实WebGL、暂停与密码显示；390px手机与减少动态效果；无WebGL时真实认证。桌面与手机截图已人工查看，产物位于output/playwright/。
- Starlette/httpx兼容层有一条弃用提示，测试未因此失败；后续需跟随上游测试客户端迁移。

Harness：dry-run成功、五次上游HTTP 200，但180秒内未产出目标文档，按规则由Codex接手。未合入任何未经审查的模型文件。

GitHub：远端读取为空仓库；已设置origin。推送预检失败：本机无可用GitHub凭据。聊天中提供的Token没有写入项目或使用；等待本机认证后推送。

## 尚未验证与风险

Docker镜像与Compose启动、局域网TLS、生产应用角色最小权限、外部审计锚定、备份恢复、吞吐量压测尚未验证。不可宣称可直接生产上线。当前登录抽象3D资产不是用户要求的弗洛洛Q版角色Logo。

## 后续阶段

1. 收尾Phase 1的系统配置、策略历史、审计摘要、生产数据库角色及部署验证。
2. Phase 2：商品分类、供应商、采购订单、采购入库、库存流水与并发闭环。
3. Phase 3：OneBot协议连接、绑定、消息去重、本地解析与确认。
4. Phase 4：可选AI、严格意图schema、工具授权与多轮状态。
5. Phase 5：审批工作流、高级权限UI与审计锚定。
6. Phase 6：销售、报表、恢复演练、性能优化和上线检查。

## 待确认业务规则

币种、税率、价格精度；负库存（未确认时拒绝）；超收与退货；审批金额阈值（未配置时拒绝高风险操作）；部门跨层级范围（默认仅直接部门）；成本与财务字段（默认隐藏）；群聊敏感信息（默认不返回）。

## Final verification supplement

Final browser regression: 4 passed (9.3s). Harness produced 8 catalog validation cases after one corrected attempt. Its missing final newline was rejected by the patch reviewer; Codex took over canonical JSON serialization after full data review and actual ProductInput validation. The 8 parameterized boundary checks passed separately. The database suite was rerun before these cases were admitted: 38 passed, 2 SQLite-only concurrency skips. Final frontend build passed. No Docker deployment or GitHub push is claimed.
