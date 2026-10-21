"use client";
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Instance = {
  id: string;
  version: number;
  name: string;
  bot_id: string;
  active: boolean;
};
type Binding = {
  id: string;
  version: number;
  instance_id: string;
  platform_user_id: string;
  active: boolean;
};
type TokenResult = { instance: Instance; access_token: string };
type Challenge = { command: string; expires_at: string };

async function call<T>(api: Api, path: string, init?: RequestInit): Promise<T> {
  return (await api(path, init)) as T;
}
function Failure({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  ) : null;
}
function field(form: FormData, name: string, trim = true) {
  const value = form.get(name);
  return typeof value === "string" ? (trim ? value.trim() : value) : "";
}
function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export default function MessagingView({ api }: { api: Api }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<unknown>();
  const [revealed, setRevealed] = useState<{
    token: string;
    note: string;
  }>();
  const [challenge, setChallenge] = useState<Challenge>();
  const instances = useQuery({
    queryKey: ["onebot_instances"],
    queryFn: () => call<{ items: Instance[] }>(api, "/onebot_instances"),
  });
  const bindings = useQuery({
    queryKey: ["message_bindings"],
    queryFn: () => call<{ items: Binding[] }>(api, "/message_bindings"),
  });
  const items = (instances.data?.items ?? []).filter(
    (r) => typeof r.id === "string" && r.id !== "***",
  );
  const active = items.filter((row) => row.active === true);
  const bindingItems = (bindings.data?.items ?? []).filter(
    (r) => typeof r.id === "string" && r.id !== "***",
  );
  function instanceName(id: string) {
    return items.find((row) => row.id === id)?.name ?? id;
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy !== undefined) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    const name = field(form, "name");
    const botId = field(form, "bot_id");
    if (!name || !botId) {
      setError(new Error("请填写实例名称与机器人 QQ"));
      return;
    }
    setBusy("create");
    setError(undefined);
    try {
      const result = await call<TokenResult>(api, "/onebot_instances", {
        method: "POST",
        body: JSON.stringify({ name, bot_id: botId }),
      });
      setRevealed({
        token: result.access_token,
        note: `实例「${name}」的访问令牌`,
      });
      element.reset();
      await qc.invalidateQueries({ queryKey: ["onebot_instances"] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }
  async function toggle(row: Instance) {
    if (busy !== undefined) return;
    setBusy("toggle:" + row.id);
    setError(undefined);
    try {
      await api("/onebot_instances/" + row.id, {
        method: "PATCH",
        body: JSON.stringify({ version: row.version, active: !row.active }),
      });
      await qc.invalidateQueries({ queryKey: ["onebot_instances"] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }
  async function rotate(row: Instance) {
    if (busy !== undefined) return;
    setBusy("rotate:" + row.id);
    setError(undefined);
    try {
      const result = await call<TokenResult>(
        api,
        "/onebot_instances/" + row.id + "/rotate_token",
        {
          method: "POST",
          body: JSON.stringify({ version: row.version }),
        },
      );
      setRevealed({
        token: result.access_token,
        note: `实例「${row.name}」的新访问令牌`,
      });
      await qc.invalidateQueries({ queryKey: ["onebot_instances"] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }
  async function requestChallenge(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy !== undefined) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    const instanceId = field(form, "instance_id");
    const platformUserId = field(form, "platform_user_id");
    const password = field(form, "password", false);
    if (!instanceId || !platformUserId || !password) {
      setError(new Error("请选择实例，并填写 QQ 号和密码"));
      return;
    }
    if (!/^\d+$/.test(platformUserId)) {
      setError(new Error("QQ 号只能包含数字"));
      return;
    }
    setBusy("challenge");
    setError(undefined);
    setChallenge(undefined);
    try {
      const result = await call<Challenge>(api, "/message_binding_challenges", {
        method: "POST",
        body: JSON.stringify({
          instance_id: instanceId,
          platform_user_id: platformUserId,
          password,
        }),
      });
      setChallenge(result);
      element.reset();
    } catch (error) {
      setError(error);
    } finally {
      const input = element.elements.namedItem("password");
      if (input instanceof HTMLInputElement) input.value = "";
      setBusy(undefined);
    }
  }
  async function revoke(row: Binding) {
    if (busy !== undefined) return;
    setBusy("revoke:" + row.id);
    setError(undefined);
    try {
      await api("/message_bindings/" + row.id + "/revoke", {
        method: "POST",
        body: JSON.stringify({ version: row.version }),
      });
      await qc.invalidateQueries({ queryKey: ["message_bindings"] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">MESSAGING / ONEBOT</span>
          <h1>消息机器人</h1>
          <p className="muted">
            管理 OneBot V11 实例与我的 QQ 绑定。消息查询复用 ERP
            权限；采购请求可在操作工作台预览并复核密码确认，群聊不回复。
          </p>
        </div>
      </div>
      <Failure error={instances.error || bindings.error || error} />
      {revealed && (
        <section className="panel padded">
          <div className="panel-heading">
            <h3>访问令牌（仅显示一次）</h3>
            <button type="button" onClick={() => setRevealed(undefined)}>
              清除令牌
            </button>
          </div>
          <p>{revealed.note}</p>
          <pre>
            <code>{revealed.token}</code>
          </pre>
          <p className="muted">
            令牌只保存在当前页面，刷新或清除后无法再次查看。请立即妥善保存；切勿把令牌拼接到
            URL 或查询参数中。
          </p>
        </section>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h3>机器人实例</h3>
          <button type="button" onClick={() => void instances.refetch()}>
            刷新
          </button>
        </div>
        {instances.isPending ? (
          <p className="empty">加载机器人实例…</p>
        ) : instances.isError ? (
          <p className="empty">机器人实例加载失败</p>
        ) : !items.length ? (
          <p className="empty">尚未创建机器人实例</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>实例 ID</th>
                  <th>机器人 QQ</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>
                      <code>{row.id}</code>
                    </td>
                    <td>{row.bot_id}</td>
                    <td>
                      {typeof row.active === "boolean"
                        ? row.active
                          ? "已启用"
                          : "已停用"
                        : "状态不可见"}
                    </td>
                    <td>
                      <div className="actions-row">
                        <button
                          type="button"
                          disabled={
                            busy !== undefined ||
                            typeof row.active !== "boolean" ||
                            typeof row.version !== "number"
                          }
                          onClick={() => void toggle(row)}
                        >
                          {busy === "toggle:" + row.id
                            ? "保存中…"
                            : row.active
                              ? "停用"
                              : "启用"}
                        </button>
                        <button
                          type="button"
                          disabled={
                            busy !== undefined ||
                            typeof row.version !== "number"
                          }
                          onClick={() => void rotate(row)}
                        >
                          {busy === "rotate:" + row.id ? "轮换中…" : "轮换令牌"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel padded">
        <h2>新建机器人实例</h2>
        <p className="muted">
          创建成功后服务端只返回一次访问令牌，用于 OneBot 反向 WebSocket 鉴权。
        </p>
        <form className="business-form" onSubmit={create}>
          <label>
            实例名称
            <input name="name" required maxLength={120} autoComplete="off" />
          </label>
          <label>
            机器人 QQ（bot_id）
            <input
              name="bot_id"
              required
              maxLength={19}
              inputMode="numeric"
              autoComplete="off"
            />
          </label>
          <button className="primary" disabled={busy !== undefined}>
            {busy === "create" ? "创建中…" : "创建实例"}
          </button>
        </form>
      </section>
      <section className="panel padded">
        <h2>绑定我的 QQ</h2>
        <p className="muted">
          选择已启用的实例生成一次性命令，再用需要绑定的 QQ 发送给机器人。
        </p>
        {instances.isPending ? (
          <p className="empty">加载可用实例…</p>
        ) : instances.isError ? (
          <p className="empty">实例加载失败，暂时无法生成绑定命令</p>
        ) : !active.length ? (
          <p className="empty">暂无已启用的实例，请先创建并启用实例</p>
        ) : (
          <form className="business-form" onSubmit={requestChallenge}>
            <label>
              机器人实例
              <select
                aria-label="机器人实例"
                name="instance_id"
                required
                defaultValue={active[0]?.id ?? ""}
              >
                {active.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}（{row.bot_id}）
                  </option>
                ))}
              </select>
            </label>
            <label>
              我的 QQ
              <input
                name="platform_user_id"
                required
                inputMode="numeric"
                pattern="[0-9]+"
                maxLength={19}
                autoComplete="off"
              />
              <small className="muted">QQ 号按字符串提交</small>
            </label>
            <label>
              当前ERP密码
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={1024}
              />
              <small className="muted">请输入当前 ERP 密码以确认绑定。</small>
            </label>
            <button className="primary" disabled={busy !== undefined}>
              {busy === "challenge" ? "生成中…" : "生成绑定命令"}
            </button>
          </form>
        )}
        {challenge && (
          <div>
            <h3>待发送的绑定命令</h3>
            <pre>
              <code>{challenge.command}</code>
            </pre>
            <p className="muted">
              有效期至：
              <time dateTime={challenge.expires_at}>
                {formatTime(challenge.expires_at)}
              </time>
              。请用指定 QQ 私聊机器人发送；重新生成会使旧命令失效。
            </p>
            <button type="button" onClick={() => setChallenge(undefined)}>
              清除命令
            </button>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h3>我的 QQ 绑定</h3>
          <button type="button" onClick={() => void bindings.refetch()}>
            刷新
          </button>
        </div>
        <p className="muted">仅显示当前账号的绑定。</p>
        {bindings.isPending ? (
          <p className="empty">加载绑定…</p>
        ) : bindings.isError ? (
          <p className="empty">绑定加载失败</p>
        ) : !bindingItems.length ? (
          <p className="empty">当前没有 QQ 绑定</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>实例</th>
                  <th>QQ</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {bindingItems.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {instanceName(row.instance_id)}
                      <small className="muted"> · {row.instance_id}</small>
                    </td>
                    <td>{row.platform_user_id}</td>
                    <td>
                      {typeof row.active === "boolean"
                        ? row.active
                          ? "生效中"
                          : "已失效"
                        : "状态不可见"}
                    </td>
                    <td>
                      {row.active === true ? (
                        <button
                          type="button"
                          disabled={
                            busy !== undefined ||
                            typeof row.version !== "number"
                          }
                          onClick={() => void revoke(row)}
                        >
                          {busy === "revoke:" + row.id ? "撤销中…" : "撤销绑定"}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel padded">
        <h2>采购请求与离线描述</h2>
        <p className="muted">
          先私聊发起采购请求，再到操作工作台预览。完整确认会创建草稿，后续提交、审批与入库仍按采购规则进行。
        </p>
        <p>
          也可私聊发送「查询一下鼠标还有多少库存」或「登记采购20个鼠标，每个35元」。单位须与商品资料一致，供应商与币种缺失时需要补充。解析失败不会调用
          AI。
        </p>
        <p>
          <code>/erp 采购 新增 商品=可见商品编码</code>
        </p>
        <p>
          <code>
            /erp 补充 请求ID 数量=2 单价=12.50 供应商=可见供应商编码 币种=CNY
          </code>
        </p>
        <p>
          <code>/erp 预览 请求ID</code> · <code>/erp 取消 请求ID</code>
        </p>
        <p className="muted">
          请求10分钟过期。消息中的确认命令会提示转Web复核密码，不会直接创建订单。
        </p>
      </section>
      <section className="panel padded">
        <h2>反向 WebSocket 接入</h2>
        <p className="muted">
          将 OneBot 11 客户端配置为反向 WebSocket（通用 /
          Universal），连接路径使用实例 ID：
        </p>
        <p>
          <code>/onebot/v11/ws/&lt;实例 ID&gt;</code>
        </p>
        <ul className="muted">
          <li>协议：OneBot 11 通用（Universal），由客户端主动连接服务端。</li>
          <li>
            鉴权：请求头 <code>Authorization: Bearer &lt;访问令牌&gt;</code>。
          </li>
          <li>
            机器人标识：请求头 <code>X-Self-ID: &lt;机器人 QQ&gt;</code>。
          </li>
          <li>
            客户端角色：请求头 <code>X-Client-Role: Universal</code>。
          </li>
        </ul>
        <p className="muted">
          令牌只能放在 Authorization 请求头中，绝不能放入反向 WebSocket 的
          URL、查询参数或日志。令牌仅在创建或轮换实例后显示一次。
        </p>
      </section>
    </>
  );
}
