# OneBot V11 接入与交互状态机

## 未发布：离线中文规则

库存查询与单商品采购描述现可在绑定后的私聊使用，例如「查询一下鼠标还有多少库存」和「登记采购20个鼠标，每个35元」。明确规则匹配失败时提示固定命令/表单，不调用AI。供应商、币种缺失继续走补充流程，单位保留并在当前授权预览/确认时核对商品基础单位。详情见[INTERACTION.md](INTERACTION.md)。Web操作工作台提供同一解析器的识别、结构化结果和受控执行入口。


## v1.0.4 采购请求与Web确认

新增持久化采购请求：消息发起可先缺少字段，使用 `/erp 补充 请求ID 字段=值` 多轮补齐，`/erp 预览 请求ID`获取当前授权预览，`/erp 取消 请求ID`取消。请求10分钟有效，参数/资料/绑定版本变化后旧摘要失效。`/erp 确认 请求ID`只提示进入Web操作工作台复核密码，不能直接创建订单。

工作台支持Web发起、列表筛选/分页、当前预览、参数补充、取消、密码确认。预览复用无写入采购计划，确认只创建draft；仍需后续提交、独立审批和入库。消息来源保存绑定版本，解绑再重绑不能恢复旧请求。详见[操作工作台](OPERATIONS.md)，版本日志见[docx/version.md](../docx/version.md)。

## 连接基础（始于v1.0.3）

支持反向 Universal WebSocket：OneBot 客户端主动连接 ERP 的 `/onebot/v11/ws/{instance_id}`。实例固定 bot ID，管理员在 Web「消息接入」创建实例后只收到一次随机访问令牌；数据库仅存 SHA-256 摘要。握手必须携带 `Authorization: Bearer <token>`、`X-Self-ID`、`X-Client-Role: Universal`。不接受 URL 查询参数或浏览器 Origin。令牌不能放在 URL、日志或策略 JSON 中。

协议参考：[反向 WebSocket](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)、[鉴权](https://github.com/botuniverse/onebot-11/blob/master/communication/authorization.md)。配置 OneBot 使用 Universal 类型和消息段数组，断线重连由 OneBot 客户端发起。Nginx 已配置该路径的 Upgrade 转发；本机开发可直连后端8000端口，生产使用受信 TLS 的 wss 地址。

实例、绑定和业务权限均通过统一权限引擎配置。升级不会自动给旧角色增加权限。新安装 bootstrap 显式建立当前资源策略。已有管理员可在权限中心为实例管理员配置 `onebot_instances` 的 read/create/update/rotate_token，令牌字段 access_token 只能 hidden/write；使用者通常只需实例 id/name/bot_id/active/version 的 read，加 `message_bindings` 自身范围的 read/create/revoke/use，以及对应采购、商品、供应商、仓库和库存的业务读取权限。消息适配器不信任 QQ 群角色、客户端提供的 ERP 用户或部门。

## 绑定与撤销

1. 已登录 ERP 用户在 Web 选择可见且启用的实例，输入预期的 QQ 号与当前 ERP 密码。
2. 服务端复核密码及当前 create 权限，签发5分钟单次绑定命令；新命令使同一用户/实例旧挑战失效，数据库只存命令摘要。
3. 用指定 QQ 在相同实例私聊发送该命令。群聊不兑换。服务端再次检查目标 QQ、实例、有效期、当前用户状态和策略，再在同一事务中建立绑定、消费挑战并记录收件箱和审计。
4. Web 可撤销自身绑定；撤销后旧平台消息不再获得业务身份，同时使该用户/实例未消费挑战失效。停用或轮换实例令牌使已有连接在处理下一帧或60秒空闲检查时失效。

一个实例下，每个平台账号和每个 ERP 用户各有唯一绑定。撤销保留记录，允许原用户重新绑定同一平台账号；变更到其他账号/转移给其他用户仍拒绝，等待后续受审计的重绑定流程。仅掌握 QQ 号不能建立绑定；管理员配置的 OneBot 实例是受信的消息来源，需保护其主机和访问令牌。

## 消息解析与查询

协议适配器只接受有界纯文本消息段数组；匿名群消息、错误 bot ID、混合媒体、重复 JSON 键和超限帧拒绝。帧上限64KiB，文本上限4096字符。生命周期/心跳、notice、request 和 API 回执不进入业务解析器。

- `/erp 库存 查询 "Mouse A"`：在有 name/id 读取权限的商品范围中匹配名称，复用 Web 库存关联范围及字段投影，最多返回20条。
- `/erp 采购 查询 [单号]`：复用 Web 采购关联范围及金额投影，最多返回20条；按单号过滤前必须具备单号可读权限。
- `/erp 采购 新增 商品=mouse 数量=20 单价=35 供应商=example 币种=CNY`：仅生成受限结构化意图。缺失字段会明确返回；本版完整意图建立待确认请求，须通过Web预览及密码复核后创建草稿。

所有群聊业务消息均无回复、无业务执行；不会把私密结果发到群里。仅私聊且当前绑定有效、用户启用并具备 bindings.use 时可进入业务查询。权限变更、显式拒绝、字段隐藏/脱敏和需要审批的读取，均在当前数据库策略下重新判断；没有缓存旧数据供重放。

## 事务、去重、限流和审计

适配器调用应用网关，网关先锁 authorization_gate。稳定 event_key（实例、bot、聊天对象、发送者、message_id）作为收件箱主键，另保存 payload_digest；成功或拒绝、绑定变更、收件箱及审计同事务提交。重复事件不重复执行或再次发送旧结果，同键不同内容拒绝并断开连接。失败回滚不会留下半完成绑定；意外失败先回滚，再尝试单独追加失败审计。

收件箱采用数据库 UPDATE/DELETE/TRUNCATE 防修改策略（SQLite 不提供 TRUNCATE），不保存原文、查询结果、令牌或绑定码。实例每分钟300条、实例内单用户每分钟30条；超限事件记为 rate_limited，不执行且不回复。绑定挑战每用户每分钟最多5次；密码复核失败沿用账号锁定保护。

回复仅在数据库提交后，向当前 Universal 连接发送 `send_private_msg` 请求。当前未持久化回复发送队列、未跟踪 API 回执确认，因此可能已处理但回复丢失；不承诺消息投递恰好一次。收件箱/挑战的保留和清理策略尚待配置，不能随意清理去重历史。

## 后续范围

尚未实现主动连接 OneBot 正向 WebSocket、独立 API/Event 双连接、连接状态监控后台、自由自然语言补充、消息直接落单和 AI。目标会话仍为 idle → parsing → collecting_missing → preview → awaiting_confirmation → executing → completed；等待态允许取消/超时，确认必须绑定参数摘要、当前主体、实例与有效期，执行前重查权限和资源状态。

实际验证包含 ASGI WebSocket、真实回环 TCP WebSocket、PostgreSQL 重复消息并发、Web/消息相同数据范围和字段投影。尚未连接真实 QQ/生产 OneBot 实例，也未验证 Docker/Linux/TLS 环境。
