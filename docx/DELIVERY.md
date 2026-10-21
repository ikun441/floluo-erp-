# OneBot连接租约与可靠回复（v1.0.5已实现）

[文档导航](README.md) · [版本日志](version.md)

## 数据关系与边界

业务消息、不可变MessageInbox和MessageDelivery在同一authorization_gate事务提交。Delivery.event_key唯一外键指向Inbox；instance_id指向OneBotInstance，owner_id可空指向ERP用户，binding_id/版本成对保存平台绑定快照。重放只查收件箱，不再执行业务或再建Delivery。

OneBotConnection以instance_id唯一关联实例，记录连接UUID、实例配置版本、连接/最后收帧时间、90秒租约、断开时间与固定原因码。仅同一实例的一个未过期连接拥有发送权。新连接只能接管已断开/过期/旧配置版本的记录；旧连接不能续租、收回执或关闭新连接。

| 表 | 核心字段与约束 |
| --- | --- |
| onebot_connection | id/version/timestamps、唯一instance_id、connection_id、instance_version、state(connected/disconnected)、connected_at、last_seen_at、lease_expires_at、disconnected_at、disconnect_reason |
| message_delivery | id/version/timestamps、唯一event_key、instance_id、recipient_id、可空owner/binding快照、recipe JSON、state、attempts(0..3)、next_attempt_at、expires_at、attempt_token/connection_id、delivered_at、last_error |

新增独立Alembic迁移；不修改旧迁移。已有收件箱不补发，升级只为新事件创建队列。队列/连接数据存在时拒绝破坏性降级。监控资源仅read，通过统一策略和实例id可读关系过滤；recipe、平台收件人、凭据、原始文本、业务结果和连接内部令牌不进入Web监控字段。

## 发送与权限

持久化recipe仅支持query(资源白名单及字符串参数)、operation(请求ID)、固定安全提示。禁止存完整业务回复或原始消息。每次尝试重查实例、连接租约、用户状态、绑定版本及bindings.use，再用相同业务服务的SQL范围/字段投影重新生成查询或当前请求详情；不重新执行采购创建。业务读取权限变化后重新过滤/脱敏；身份或请求授权不足时suppressed并清空recipe。

固定denied/binding_required/unsupported提示不包含业务数据，可在身份失效时安全发送；绑定成功提示要求原绑定仍有效。pending/awaiting_ack最长5分钟、每实例最多1000条非终态、最多3次尝试。发送前先持久化attempt_token与连接UUID，成功发送后等待15秒API回执；失败或超时按5秒/15秒等有界退避重试。重连会接管旧连接未确认任务。终态delivered/failed/suppressed/expired清除recipe。

唯一echo匹配当前尝试及当前连接，且status=ok、retcode为整数0才标记delivered。async/1不算已送达，等待确认/超时；失败码只保存固定原因，不保存模型/平台返回消息。此处delivered仅表示OneBot API成功，不证明QQ用户已读。API缺乏发送幂等键，回执丢失时重试可能重复发送；不承诺恰好一次。

## 运行与可见性

反向Universal连接内进行有界轮询/发送，不增加Redis/Celery运行依赖。进程退出后的状态由90秒租约失效；服务恢复且OneBot重连后从数据库接续。收帧刷新last_seen，租约定期续期；客户端负责反向重连。断开和旧连接finally处理均需UUID比较，防止误伤新连接。

Web消息接入新增连接监控与回复队列，只读分页/状态筛选，显式新资源授权，不自动扩大旧角色。租约过期展示为失联；失败原因使用固定标签。没有手工强制补发或绕过当前权限的入口。

真实QQ、Linux容器和多进程生产验收仍单独记录；保留/清理与通知outbox消费者不在本阶段范围。

协议依据：[WebSocket](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)、[反向连接](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)、[公共API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)。
