"use client";
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Configuration = {
  version?: number;
  enabled?: boolean;
  base_url?: string;
  model?: string;
  timeout_seconds?: number;
  tools?: string[];
  allowed_base_urls?: string[];
  credential_configured?: boolean;
};
const tools = {
  query_inventory: "库存查询",
  query_purchase_orders: "采购订单查询",
  query_sales_summary: "销售汇总",
};
function Editor({
  api,
  current,
  done,
}: {
  api: Api;
  current: Configuration;
  done: () => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(current.enabled ?? false);
  const [base, setBase] = useState(current.base_url ?? "");
  const [model, setModel] = useState(current.model ?? "");
  const [timeout, setTimeoutValue] = useState(current.timeout_seconds ?? 10);
  const [selected, setSelected] = useState(current.tools ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await api("/ai/configuration", {
        method: "PATCH",
        body: JSON.stringify({
          version: current.version,
          values: {
            enabled,
            base_url: base,
            model,
            timeout_seconds: timeout,
            tools: selected,
          },
        }),
      });
      await done();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "配置保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="ai-config-form" onSubmit={save}>
      <label className="ai-check">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        启用可选 AI 服务
      </label>
      <label>
        模型服务地址
        <select
          value={base}
          onChange={(event) => setBase(event.target.value)}
          aria-label="模型服务地址"
        >
          <option value="">选择部署管理员允许的地址</option>
          {current.allowed_base_urls?.map((url) => (
            <option key={url} value={url}>
              {url}
            </option>
          ))}
        </select>
      </label>
      {!current.allowed_base_urls?.length && (
        <p className="muted">
          尚未配置允许的服务地址，请由部署管理员设置 AI_ALLOWED_BASE_URLS。
        </p>
      )}
      <label>
        模型名称
        <input
          maxLength={120}
          value={model}
          onChange={(event) => setModel(event.target.value)}
          placeholder="填写服务支持的模型名称"
        />
      </label>
      <label>
        请求超时（秒）
        <input
          type="number"
          min={2}
          max={20}
          value={timeout}
          onChange={(event) => setTimeoutValue(Number(event.target.value))}
          required
        />
      </label>
      <fieldset>
        <legend>允许 AI 使用的查询工具</legend>
        {Object.entries(tools).map(([key, name]) => (
          <label className="ai-check" key={key}>
            <input
              type="checkbox"
              checked={selected.includes(key)}
              onChange={(event) =>
                setSelected(
                  event.target.checked
                    ? [...selected, key]
                    : selected.filter((value) => value !== key),
                )
              }
            />
            {name}
          </label>
        ))}
      </fieldset>
      <p className="muted">
        工具开关限定 AI 的能力范围，用户仍需对应的数据读取与 ai_query
        权限；销售汇总还需 report。修改配置后，旧解析预览需要重新生成。
      </p>
      <p className="muted">
        API 密钥：
        {current.credential_configured === true
          ? "部署侧已配置"
          : current.credential_configured === false
            ? "未配置（无认证的本地模型可留空）"
            : "当前字段不可见或已脱敏"}
        。密钥通过服务端 AI_API_KEY 管理。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" disabled={busy}>
        {busy ? "保存中…" : "保存 AI 配置"}
      </button>
    </form>
  );
}
export default function AIConfigurationView({ api }: { api: Api }) {
  const client = useQueryClient();
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: ["ai", "configuration"],
    queryFn: () => api("/ai/configuration") as Promise<Configuration>,
  });
  const config = !query.isError && !query.isFetching ? query.data : undefined;
  const editable =
    config &&
    typeof config.version === "number" &&
    typeof config.enabled === "boolean" &&
    typeof config.base_url === "string" &&
    typeof config.model === "string" &&
    config.base_url !== "***" &&
    config.model !== "***" &&
    typeof config.timeout_seconds === "number" &&
    Array.isArray(config.tools) &&
    Array.isArray(config.allowed_base_urls);
  return (
    <>
      <div className="section-heading">
        <div>
          <p className="eyebrow">OPTIONAL INTELLIGENCE</p>
          <h1>AI 服务配置</h1>
          <p className="muted">按需启用，核心业务始终支持离线操作。</p>
        </div>
      </div>
      <section className="panel padded">
        <h2>模型与查询工具</h2>
        {saved && <p role="status">AI 配置已保存。</p>}
        {query.error && (
          <p className="error" role="alert">
            {query.error instanceof Error
              ? query.error.message
              : "无法读取配置"}
          </p>
        )}
        {query.isFetching ? (
          <p role="status">正在校验配置权限…</p>
        ) : editable ? (
          <Editor
            key={config.version}
            api={api}
            current={config}
            done={async () => {
              await client.invalidateQueries({ queryKey: ["ai"] });
              setSaved(true);
            }}
          />
        ) : config ? (
          <p className="muted">
            当前配置字段不完整可读，请联系管理员核对字段权限。
          </p>
        ) : null}
      </section>
    </>
  );
}
