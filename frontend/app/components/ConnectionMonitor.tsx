"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Instance = {
  id: string;
  name?: string;
  active?: boolean;
  version?: number;
};
type RecordRow = {
  id?: string;
  instance_id?: string;
  instance_version?: number;
  state?: string;
  last_seen_at?: string;
  lease_expires_at?: string;
  disconnect_reason?: string;
  attempts?: number;
  next_attempt_at?: string;
  last_error?: string;
};
const states: Record<string, string> = {
  pending: "等待发送",
  awaiting_ack: "等待回执",
  delivered: "API 成功",
  failed: "已失败",
  suppressed: "已拦截",
  expired: "已过期",
};
const reasons: Record<string, string> = {
  peer_closed: "客户端断开",
  protocol_error: "协议数据错误",
  transport_error: "连接异常",
  auth_changed: "鉴权或配置变化",
  queue_limit: "队列达到上限",
  authorization_changed: "权限或绑定变化",
  invalid_recipe: "回复参数无效",
  ttl_expired: "超过有效期",
  ack_timeout: "回执超时",
  api_failed: "平台 API 失败",
  attempt_limit: "达到重试上限",
  async_unconfirmed: "异步结果未确认",
};
function time(value: unknown) {
  if (typeof value !== "string" || value === "***") return "不可见";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "不可见"
    : parsed.toLocaleString("zh-CN");
}
function visible(rows: RecordRow[] | undefined) {
  return (rows ?? []).filter((r) => typeof r.id === "string" && r.id !== "***");
}
function Failure({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : "监控加载失败，请重试"}
    </p>
  ) : null;
}
export default function ConnectionMonitor({
  api,
  instances,
}: {
  api: Api;
  instances: Instance[];
}) {
  const [state, setState] = useState("");
  const [after, setAfter] = useState("");
  const connections = useQuery({
    queryKey: ["onebot_connections"],
    refetchInterval: 5000,
    queryFn: async () =>
      (await api("/onebot_connections?limit=100")) as { items: RecordRow[] },
  });
  const deliveries = useQuery({
    queryKey: ["message_deliveries", state, after],
    refetchInterval: 5000,
    queryFn: async () =>
      (await api(
        "/message_deliveries?limit=50" +
          (state ? "&state=" + state : "") +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      )) as { items: RecordRow[] },
  });
  const rows = visible(deliveries.data?.items);
  function instanceName(id: string | undefined) {
    return (
      instances.find((r) => r.id === id)?.name ??
      (id === "***" || !id ? "实例不可见" : id)
    );
  }
  function connectionStatus(row: RecordRow) {
    if (row.state === "disconnected") return "离线";
    if (
      row.state !== "connected" ||
      !row.lease_expires_at ||
      row.lease_expires_at === "***"
    )
      return "状态不可见";
    const expiry = Date.parse(row.lease_expires_at);
    if (!Number.isFinite(expiry)) return "状态不可见";
    if (expiry <= Date.now()) return "连接已失联";
    const instance = instances.find((r) => r.id === row.instance_id);
    if (instance?.active === false) return "实例已停用";
    if (
      typeof instance?.version !== "number" ||
      typeof row.instance_version !== "number"
    )
      return "状态不可见";
    return instance.version === row.instance_version ? "在线" : "配置已变化";
  }
  return (
    <section
      className="panel padded connection-monitor"
      aria-label="连接与回复监控"
    >
      <div className="panel-heading">
        <h2>连接与回复监控</h2>
        <button
          type="button"
          disabled={connections.isFetching || deliveries.isFetching}
          onClick={() =>
            void Promise.all([connections.refetch(), deliveries.refetch()])
          }
        >
          刷新监控
        </button>
      </div>
      <p className="muted">
        每5秒刷新。未确认回复会在重连后继续尝试，最多3次；API
        成功不代表对方已读。
      </p>
      <Failure error={connections.error || deliveries.error} />
      <h3>连接状态</h3>
      {connections.isPending ? (
        <p className="empty">正在加载连接…</p>
      ) : !visible(connections.data?.items).length ? (
        <p className="empty">
          暂无可见连接记录。请确认监控权限，并让 OneBot 客户端建立连接。
        </p>
      ) : (
        <div className="table-wrap">
          <table aria-label="连接状态表">
            <thead>
              <tr>
                <th>实例</th>
                <th>连接状态</th>
                <th>最后活动</th>
                <th>连接有效至</th>
                <th>断开原因</th>
              </tr>
            </thead>
            <tbody>
              {visible(connections.data?.items).map((row) => (
                <tr key={row.id}>
                  <td>{instanceName(row.instance_id)}</td>
                  <td>
                    <span className="badge">{connectionStatus(row)}</span>
                  </td>
                  <td>{time(row.last_seen_at)}</td>
                  <td>{time(row.lease_expires_at)}</td>
                  <td>
                    {row.disconnect_reason
                      ? (reasons[row.disconnect_reason] ?? "原因不可见")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="panel-heading delivery-heading">
        <h3>回复投递</h3>
        <label>
          投递状态
          <select
            aria-label="投递状态"
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setAfter("");
            }}
          >
            <option value="">全部状态</option>
            {Object.entries(states).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {deliveries.isPending ? (
        <p className="empty">正在加载投递记录…</p>
      ) : !rows.length ? (
        <p className="empty">暂无当前筛选下可见的投递记录。</p>
      ) : (
        <div className="table-wrap">
          <table aria-label="回复投递表">
            <thead>
              <tr>
                <th>实例</th>
                <th>状态</th>
                <th>尝试次数</th>
                <th>下次尝试 / 回执期限</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{instanceName(row.instance_id)}</td>
                  <td>
                    {row.state
                      ? (states[row.state] ?? "状态不可见")
                      : "状态不可见"}
                  </td>
                  <td>
                    {typeof row.attempts === "number"
                      ? `${row.attempts} / 3`
                      : "不可见"}
                  </td>
                  <td>
                    {row.state === "pending" || row.state === "awaiting_ack"
                      ? time(row.next_attempt_at)
                      : "—"}
                  </td>
                  <td>
                    {row.last_error
                      ? (reasons[row.last_error] ?? "原因不可见")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pagination">
        <button type="button" disabled={!after} onClick={() => setAfter("")}>
          投递首页
        </button>
        <button
          type="button"
          disabled={rows.length < 50 || deliveries.isFetching}
          onClick={() => setAfter(rows[rows.length - 1]?.id ?? "")}
        >
          下一页投递
        </button>
      </div>
    </section>
  );
}
