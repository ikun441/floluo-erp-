# 消息适配与交互状态机（设计，Phase 3）

adapter 验证连接鉴权与实例来源 → inbox 按 instance/event_id 唯一去重 → verified binding → parser → application command。

连接：disabled → connecting → authenticating → online → backoff；指数退避带抖动，Reverse WS 在接收任何业务消息前完成鉴权。仅使用 OneBot 号码不能授权；绑定需要已登录 ERP 用户生成单次短期挑战，再由同一协议实例私聊兑换。

会话：idle → parsing(local command → local rules) → collecting_missing → preview → awaiting_confirmation → executing → completed；任意等待态可 cancelled/expired；低置信度 → asking_ai_consent → ai_parsing → preview。用户确认后重新读取身份、资源和权限；确认绑定 canonical command 摘要、用户、绑定实例、过期时间，参数变更需重新确认。

高风险操作需额外身份确认，群聊默认只返回非敏感状态，详情转已绑定私聊或 Web。AI 失败保留固定命令路径。消息重复不重复执行，幂等结果只返回给原主体；日志不默认存原文。
