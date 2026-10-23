# 开发协作与视觉设计

[文档导航](README.md) · [版本日志](version.md) · [当前验收](IMPLEMENTATION.md)

当前范围以实施记录为准；下文保留必要的架构、升级与历史依据。

[Harness协作记录](#harness) · [登录页与动效](#login) · [品牌资源](#branding)

<a id="harness"></a>

## Harness协作记录

2026-10-20: re-read the repaired dsh-delegator skill. Default host-side Bailian broker keeps provider credentials outside the DSH child, binds an ephemeral loopback port and restricts sandbox outbound access to that port. Existing skill validation records report a successful live model and reviewed fixture edit. This is not yet proof of a successful ERP task.

ERP delegation: exact glossary path only (now [docx/GLOSSARY.md](INTERACTION.md#glossary)), three non-sensitive design documents as context, no runtime template or broad gateway_network override. Codex reviews the complete patch and runs trusted checks before digest-gated application. Provider keys are never included in project files or prompts. The temporary broker is accessible to other local processes during its lifetime; it is not a multi-user service.

ERP first real task result: dry-run passed; five upstream HTTP 200 responses; no final event before the 180-second deadline. Result takeover_required / timeout, no target file created and nothing merged. Codex takes over the glossary task. This proves route connectivity, not successful ERP delegation.

Catalog fixture task: first candidate had no changes and was rejected. One corrected attempt produced exactly the authorized JSON file with eight cases. The patch reviewer rejected its missing final newline, as designed. Codex reviewed all data, checked all eight outcomes against the actual ProductInput schema and boundary lengths, then took over canonical JSON serialization with a newline. No automatic patch was applied and no review rule was relaxed. A private review receipt retains the original artifact SHA256.

Procurement boundary fixtures: used an independent clean source worktree so core implementation could continue without changing the delegated source revision. First attempt lacked an exported parent directory and created no target. Its trusted check also exposed that runtime/bin/node requires a desktop-only environment variable. The second and final attempt exported one safe JSON context to provision the directory and selected the actual Electron executable in Node mode. It produced exactly the intended 12 cases, but the reviewer rejected the missing final newline before running checks. No automatic patch was applied. Codex inspected the entire JSON, validated all 12 expected outcomes against the real LineInput schema, and took over canonical serialization. The original and normalized hashes are retained in a private review receipt. The JSON does not contain business records or credentials. No sandbox rules were relaxed.

v1.0.3 message UI: an isolated exact-file task timed out at300 seconds; report remained takeover_required, not a successful candidate. A complete MessagingView.tsx was present in the retained worktree. Codex read the entire untrusted file, took over integration, corrected hidden-field guards and password/one-time-secret handling, then ran project TypeScript, formatting, build and real-browser checks. No report status was altered and no digest-gated auto-apply was used; a private SHA256 receipt records the original partial artifact. The timeout is not counted as successful Harness execution. Further retries for this task were stopped.

v1.0.4 OperationsView: an exact-file isolated task timed out at240 seconds and no candidate existed. Codex took over implementation, with no automatic retry or relaxed sandbox. The task was not counted as successful delegation. Core migration, preview/confirmation authorization and transactions remained with Codex.

离线规则样例任务：2026-10-21，精确授权tests/fixtures/local_intent_cases.json，180秒超时，两个上游200响应，无候选文件。未应用任何DSH产物，也未放宽沙箱或重试；Codex接管有边界的样例与可信回归测试。此任务不计为成功委派。

v1.0.5回执样例任务未得到可审查报告或候选文件，未采用任何产物，不计为成功委派；没有放宽隔离。最终回执、连接、并发和权限测试由Codex实现并真实运行。

v1.0.6销售金额样例：精确授权tests/fixtures/sales_amount_cases.json，隔离dry-run通过。headless返回needs_codex_review，但review实际changed为空，指定JSON检查退出69，tests_passed=false；未应用候选、未调整报告或隔离。Codex接管八例样本与真实金额校验，不计为成功委派。

<a id="harness-v108-文档整理尝试2026-10-22"></a>

### v1.0.8 文档整理尝试（2026-10-22）

使用dsh-delegator，为单个docx/REPORTS.md安排中文可读性整理，只有该文件可写，无密钥或业务数据上下文。dry-run验证通过；隔离执行配置timeout=90/retries=0，返回takeover_required/timeout、attempts=[]，没有可审查产物。没有自动重试或扩大隔离权限，Codex接管文档整理与验收。任务与报告保留在仓库外私有临时目录，不提交运行会话。

<a id="harness-v1010-ai使用说明尝试2026-10-23"></a>

### v1.0.10 AI使用说明尝试（2026-10-23）

限定docx/AI_WORKFLOW.md，安全上下文仅旧AI说明，timeout=120/retries=0；dry-run通过，三个上游HTTP200，headless返回needs_codex_review。可信review生成空patch（changed=[]），指定文件存在性检查退出71、tests_passed=false，没有集成任何候选。未放宽隔离或自动重试，由Codex接管使用说明，核心实现和最终测试仍由Codex负责。此轮不计成功委派。

<a id="login"></a>

## 登录页与动效

<a id="login-方向"></a>

### 方向

暗色空间与明亮表单并置；自建 Three.js 玻璃雕塑、轨道、卫星与粒子，Motion 分层入场，鼠标视差、按钮聚光、密码显示、等待与成功反馈。全部几何体、环境光与粒子在本地生成，不需要外部模型、字体或图片服务。

设计参考：

- [Awwwards / Noomo 3D Portal](https://www.awwwards.com/inspiration/3d-portal-noomo-valentime)：玻璃材质与空间层次。
- [Codrops / Glass Effect](https://tympanus.net/Tutorials/GlassEffect/)：光线、透明感与实体空间。
- [Motion / reduced motion](https://motion.dev/docs/react-use-reduced-motion)：尊重系统减少动态效果偏好。

参考用于视觉方向，没有复制站点素材。抽象雕塑保留为登录页背景视觉。v1.0.3已接入用户提供的Q版原始PNG作为品牌Logo，登录页、工作台和浏览器图标统一使用该资源，见BRANDING.md。

<a id="login-运行边界"></a>

### 运行边界

3D 模块按需加载；像素比受限，绘制节流为最多30帧/秒；后台页面停止绘制。提供暂停背景动效按钮；系统减少动态效果模式禁用连续运动。组件卸载释放 GPU 几何、材质、环境贴图与上下文。WebGL 不可用时使用 CSS 图形降级，登录表单和真实认证继续工作。

登录成功后重新加载当前用户，清除其他用户数据缓存；服务端认证、CSRF 和权限边界不受动画影响。动画不代替身份验证，也不显示虚构业务统计。

<a id="login-验证入口"></a>

### 验证入口

前端 `npm run typecheck`、`npm run build`。
浏览器自动化见 `scripts/testing/e2e/login.spec.ts`，覆盖真实登录/登出、部门保存与刷新、权限页面、WebGL 场景、暂停、密码显示、移动端、减少动态效果及无 WebGL 降级。

<a id="branding"></a>

## 品牌资源

2026-10-21由用户提供并授权同步本项目的原始PNG，位于 `frontend/public/brand/floluo-logo.png`。1254×1254、RGBA，保留原内容、透明度和比例，没有裁切、重绘或改字。

原图SHA-256：`e5d4849440da2b79a881f898946a93cc95767d4e1c65c949d2866bf8ffb47eda`。

用于登录页品牌标识/欢迎图、工作台侧栏、浏览器与Apple图标、README。页面通过CSS等比显示；运行时使用本地静态文件，无外部图片服务。standalone启动脚本和Docker前端均包含public资源，避免生产模式404。

后续替换或衍生图需保持来源记录，不能用其他图自动替换用户指定Logo。
