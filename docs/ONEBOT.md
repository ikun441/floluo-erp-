# OneBot V11 接入与交互状态机

## 当前实现

`backend/erp/onebot` 是独立协议边界，不依赖 ERP ORM，也不执行业务操作。

- `intent.py` 提供有长度上限的 `/erp` 固定命令解析：库存查询、采购单查询，以及生成待补全的采购新增意图。参数采用允许列表；重复键、未知键、非法数量/金额、非 ASCII 币种均拒绝。缺失字段作为结构化结果返回，不推断供应商或默认币种。
- 解析结果是惰性的 `BusinessIntent`，只描述 operation、resource、arguments、references、confidence 和 parser_source。生成意图不代表授权或执行；后续执行必须走统一身份、权限引擎和业务服务。
- `events.py` 校验 OneBot V11 私聊/群聊消息事件，要求配置的 bot ID 匹配，并只接受有界的纯文本消息段数组。消息键按实例、bot、聊天类型/对象、发送者和 message_id 稳定计算；另保留 payload digest，供将来的持久化收件箱检测同键不同内容。平台 sender.role 等元数据不构成 ERP 身份或权限。
- `tests/test_onebot_foundation.py` 覆盖固定命令样例、重复/未知参数、数值边界、bot 身份不匹配、匿名群消息、非文本段、消息长度与事件键范围。

## 尚未实现

当前没有 WebSocket 或 Reverse WebSocket 监听器、连接来源鉴权/自动重连、ERP 用户绑定、数据库收件箱及原子去重、会话状态存储、多轮补充、预览/确认、权限授权执行或消息回复发送端。也没有 AI 解析接入。群聊事件目前只可被规范化，系统不会因此回复或执行操作。不得将收到 QQ 号码或群角色视为已经验证的 ERP 用户身份。

## 目标连接与身份流程

adapter 验证连接鉴权与实例来源 → inbox 按 instance/event_id 唯一去重 → verified binding → parser → application command。

连接：disabled → connecting → authenticating → online → backoff；指数退避带抖动，Reverse WS 在接收任何业务消息前完成鉴权。绑定需要已登录 ERP 用户生成单次短期挑战，再由同一协议实例私聊兑换。

会话：idle → parsing(local command → local rules) → collecting_missing → preview → awaiting_confirmation → executing → completed；任意等待态可 cancelled/expired；低置信度且取得用户同意后才可进入 AI 解析。用户确认后重新读取身份、资源和权限；确认绑定 canonical command 摘要、用户、绑定实例和过期时间，参数变更需重新确认。

高风险操作需额外身份确认。群聊默认不返回敏感业务信息，详情应转至已绑定私聊或 Web。解析器不得连接数据库或绕过权限服务；消息处理与 Web 共用同一业务服务、权限引擎、审计和事务边界。原文默认不写入操作日志。
