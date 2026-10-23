"use client";
import { useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, RefreshCw } from "lucide-react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Intent = {
  operation: "query" | "create";
  resource: string;
  arguments: Record<string, string>;
  confidence: number;
  parser_source: string;
};
type RequestRow = {
  id?: string;
  version?: number;
  state?: string;
  intent?: Intent | "***" | null;
  expires_at?: string;
  error_code?: string;
};
const states: Record<string, string> = {
  parsing: "正在理解",
  ready: "等待确认查询",
  clarification: "需要重新描述",
  failed: "理解失败",
  cancelled: "已取消",
};
const resources: Record<string, string> = {
  inventory: "库存",
  purchase_orders: "采购订单",
  sales_summary: "销售汇总",
};
const names: Record<string, string> = {
  query: "商品名称",
  number: "订单号",
  metric: "指标",
  status: "状态",
  currency: "币种",
  id: "标识",
  version: "版本",
  warehouse_id: "仓库 ID",
  product_id: "商品 ID",
  quantity: "数量",
  total: "金额",
  supplier_id: "供应商 ID",
  lines: "商品明细",
  owner_id: "归属用户",
  department_id: "部门",
  approved_by: "审批人",
  note: "备注",
  amount: "订单金额",
  source_rows: "来源记录数",
};
function valid(row: RequestRow) {
  return (
    typeof row.id === "string" &&
    row.id !== "***" &&
    typeof row.version === "number"
  );
}
function describe(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function Result({
  api,
  path,
  body,
  identity,
}: {
  api: Api;
  path: string;
  body: object;
  identity: string;
}) {
  const query = useQuery({
    queryKey: ["ai", "result", identity],
    queryFn: () =>
      api(path, { method: "POST", body: JSON.stringify(body) }) as Promise<{
        result?: { items: Record<string, unknown>[]; limit?: number };
        limit?: number;
        items?: Record<string, unknown>[];
      }>,
  });
  const data = !query.isError && !query.isFetching ? query.data : undefined;
  const items = data?.result?.items ?? data?.items ?? [];
  const order = [
    "number",
    "status",
    "currency",
    "quantity",
    "total",
    "amount",
    "source_rows",
    "product_id",
    "warehouse_id",
    "id",
    "version",
    "supplier_id",
    "owner_id",
    "department_id",
    "lines",
    "note",
  ];
  const columns = Array.from(
    new Set(items.flatMap((row) => Object.keys(row))),
  ).sort(
    (a, b) =>
      (order.includes(a) ? order.indexOf(a) : 100) -
      (order.includes(b) ? order.indexOf(b) : 100),
  );
  return (
    <section className="panel" aria-label="助手查询结果">
      <div className="panel-heading">
        <h2>当前权限下的查询结果</h2>
        <button
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCw size={15} />
          重新查询
        </button>
      </div>
      {query.error && (
        <p className="error" role="alert">
          {query.error instanceof Error ? query.error.message : "查询失败"}
        </p>
      )}
      {query.isFetching ? (
        <p className="empty" role="status">
          正在重新校验权限并查询…
        </p>
      ) : data ? (
        !items.length ? (
          <p className="empty">当前授权范围内没有可显示的记录。</p>
        ) : (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">当前授权范围的业务查询结果</caption>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th key={column} scope="col">
                      {names[column] ?? column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((row, index) => (
                  <tr key={index}>
                    {columns.map((column) => (
                      <td
                        key={column}
                        data-numeric={[
                          "quantity",
                          "total",
                          "amount",
                          "source_rows",
                        ].includes(column)}
                      >
                        <span className="ai-cell">{describe(row[column])}</span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
      <p className="ai-help">
        结果由 ERP 按当前账号权限查询并直接展示，不回传模型。
        {(data?.result?.limit ?? data?.limit) &&
          `最多展示 ${data?.result?.limit ?? data?.limit} 条记录，不代表全部记录总量。`}
      </p>
    </section>
  );
}
function Preview({ intent }: { intent: Intent }) {
  return (
    <dl className="ai-preview">
      <dt>业务对象</dt>
      <dd>{resources[intent.resource] ?? intent.resource}</dd>
      <dt>操作</dt>
      <dd>{intent.operation === "query" ? "查询" : "创建待确认请求"}</dd>
      {Object.entries(intent.arguments).map(([key, value]) => (
        <div className="ai-preview-row" key={key}>
          <dt>{names[key] ?? key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
      <dt>识别来源</dt>
      <dd>{intent.parser_source === "ai" ? "AI 辅助理解" : "离线规则"}</dd>
    </dl>
  );
}
export default function AIAssistantView({
  api,
  openOperations,
}: {
  api: Api;
  openOperations: () => void;
}) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [local, setLocal] = useState<{ intent: Intent; text: string }>();
  const [unsupported, setUnsupported] = useState<string>();
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const [confirmed, setConfirmed] = useState<string>();
  const [localConfirmed, setLocalConfirmed] = useState(false);
  const attempt = useRef<{ key: string; text: string } | undefined>(undefined);
  const status = useQuery({
    queryKey: ["ai", "status"],
    queryFn: () => api("/ai/status") as Promise<{ enabled: boolean }>,
  });
  const history = useQuery({
    queryKey: ["ai", "requests"],
    queryFn: () => api("/ai/requests") as Promise<{ items: RequestRow[] }>,
    refetchInterval: busy ? 2000 : false,
  });
  const detail = useQuery({
    queryKey: ["ai", "request", selected],
    queryFn: () => api("/ai/requests/" + selected) as Promise<RequestRow>,
    enabled: !!selected,
  });
  const row = !detail.isError && !detail.isFetching ? detail.data : undefined;
  const preview =
    row?.intent && typeof row.intent === "object" ? row.intent : undefined;
  const token = row && valid(row) ? row.id + ":" + row.version : undefined;
  async function offline(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    setSelected(undefined);
    setConfirmed(undefined);
    setLocal(undefined);
    setLocalConfirmed(false);
    setUnsupported(undefined);
    setConsent(false);
    attempt.current = undefined;
    try {
      const result = (await api("/intents/parse", {
        method: "POST",
        body: JSON.stringify({ text }),
      })) as { intent: Intent };
      setLocal({ intent: result.intent, text });
    } catch (failure) {
      if ((failure as { status?: number }).status === 422) setUnsupported(text);
      else
        setError(
          failure instanceof Error ? failure.message : "离线识别失败，请重试",
        );
    } finally {
      setBusy(false);
    }
  }
  async function parseAI() {
    if (!unsupported || !consent || busy) return;
    const original = attempt.current ?? {
      key: Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
        value.toString(16).padStart(2, "0"),
      ).join(""),
      text: unsupported,
    };
    attempt.current = original;
    setBusy(true);
    setError(undefined);
    setSelected(undefined);
    setConfirmed(undefined);
    try {
      const response = (await api("/ai/requests", {
        method: "POST",
        headers: { "Idempotency-Key": original.key },
        body: JSON.stringify({ text: original.text, consent: true }),
      })) as RequestRow;
      if (valid(response)) setSelected(response.id);
      attempt.current = undefined;
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "网络结果未知，可使用原请求重试。",
      );
      if (
        typeof (failure as { status?: number }).status === "number" &&
        (failure as { status?: number }).status !== 409
      )
        attempt.current = undefined;
    } finally {
      setBusy(false);
      await client.invalidateQueries({ queryKey: ["ai", "requests"] });
    }
  }
  async function cancel(item: RequestRow) {
    if (!valid(item)) return;
    try {
      await api("/ai/requests/" + item.id + "/cancel", {
        method: "POST",
        body: JSON.stringify({ version: item.version }),
      });
      setConfirmed(undefined);
      await client.invalidateQueries({ queryKey: ["ai"] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "取消失败");
    }
  }
  const enabled = !status.isError && !status.isFetching && status.data?.enabled;
  const recent =
    !history.isError && !history.isFetching ? (history.data?.items ?? []) : [];
  return (
    <div className="ai-assistant">
      <div className="section-heading">
        <div>
          <p className="eyebrow">ASSISTED WORKSPACE</p>
          <h1>AI 助手</h1>
          <p className="muted">先离线理解，再按需借助 AI；每次查询由你确认。</p>
        </div>
        <Sparkles size={29} aria-hidden="true" />
      </div>
      <section className="panel padded">
        <h2>描述你想了解的业务</h2>
        <form onSubmit={offline} className="ai-description">
          <label htmlFor="ai-description">业务描述</label>
          <textarea
            id="ai-description"
            rows={3}
            maxLength={4096}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setUnsupported(undefined);
              setConsent(false);
              setLocal(undefined);
              setSelected(undefined);
              setConfirmed(undefined);
              setLocalConfirmed(false);
              attempt.current = undefined;
            }}
            disabled={busy}
            required
            placeholder="例如：请帮我看看某件商品的库存是否还够用"
          />
          <button className="primary" disabled={busy}>
            {busy ? "正在理解…" : "先用离线规则理解"}
          </button>
        </form>
        {local && (
          <div className="ai-consent">
            <h3>离线规则已识别</h3>
            <Preview intent={local.intent} />
            {local.intent.operation === "query" ? (
              <button
                onClick={() => setLocalConfirmed(true)}
                disabled={localConfirmed}
              >
                确认离线查询
              </button>
            ) : (
              <button onClick={openOperations}>前往操作工作台完善请求</button>
            )}
          </div>
        )}
        {unsupported && (
          <div className="ai-consent">
            <h3>离线规则暂未识别</h3>
            <p>
              可以让 AI
              进一步理解。只发送本次业务描述；识别结果需要预览确认，业务数据不会回传模型。
            </p>
            {!enabled && (
              <p className="muted">
                AI 当前未启用，仍可使用固定命令和业务页面。
              </p>
            )}
            <label className="ai-check">
              <input
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
                disabled={busy}
              />
              我同意将本次描述发送至企业配置的模型服务
            </label>
            <button
              onClick={() => void parseAI()}
              className="primary"
              disabled={!consent || !enabled || busy}
            >
              {attempt.current ? "重试原解析请求" : "同意并使用 AI 理解"}
            </button>
          </div>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </section>
      {localConfirmed && local && local.intent.operation === "query" && (
        <Result
          key={local.text}
          api={api}
          path="/intents/query"
          body={{ text: local.text }}
          identity={"offline:" + local.text}
        />
      )}
      {selected && (
        <section className="panel padded" aria-label="AI 理解预览">
          <h2>AI 理解预览</h2>
          {detail.error && (
            <p className="error" role="alert">
              {detail.error instanceof Error
                ? detail.error.message
                : "无法读取预览"}
            </p>
          )}
          {detail.isFetching ? (
            <p role="status">正在校验预览权限…</p>
          ) : row ? (
            <>
              <p>{states[row.state ?? ""] ?? "状态不可见"}</p>
              {preview && <Preview intent={preview} />}
              {row.state === "clarification" && (
                <p className="muted">
                  模型把握不足，请补充商品名称、单号或查询目标后重新描述。
                </p>
              )}
              {row.state === "failed" && (
                <p className="error" role="alert">
                  模型理解失败，请检查服务或重新描述。
                </p>
              )}
              {row.expires_at && (
                <p className="muted">
                  预览有效至{" "}
                  {row.expires_at === "***"
                    ? "已脱敏"
                    : new Date(row.expires_at).toLocaleTimeString("zh-CN", {
                        hour12: false,
                      })}
                </p>
              )}
              {row.state === "ready" && preview && token && (
                <button
                  className="primary"
                  onClick={() => setConfirmed(token)}
                  disabled={confirmed === token}
                >
                  按当前权限确认查询
                </button>
              )}
            </>
          ) : null}
        </section>
      )}
      {row?.state === "ready" && preview && token && confirmed === token && (
        <Result
          key={token}
          api={api}
          path={"/ai/requests/" + row.id + "/execute"}
          body={{ version: row.version }}
          identity={token}
        />
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>本次会话的解析请求</h2>
          <button
            onClick={() => void history.refetch()}
            disabled={history.isFetching}
          >
            刷新请求
          </button>
        </div>
        <p className="ai-help">
          仅显示本账号、本次登录会话最近 20 条请求。重新查询会再次校验权限。
        </p>
        {history.error && (
          <p className="error" role="alert">
            {history.error instanceof Error
              ? history.error.message
              : "请求列表不可用"}
          </p>
        )}
        {!recent.length ? (
          <p className="empty">
            {history.isFetching
              ? "正在读取请求…"
              : "当前没有可显示的解析请求。"}
          </p>
        ) : (
          <ul className="ai-history">
            {recent.map((item, index) => (
              <li key={item.id ?? index}>
                <span>{states[item.state ?? ""] ?? "状态不可见"}</span>
                <div>
                  {valid(item) && (
                    <button
                      onClick={() => {
                        setSelected(item.id);
                        setConfirmed(undefined);
                      }}
                    >
                      查看理解预览
                    </button>
                  )}
                  {valid(item) &&
                    ["parsing", "ready", "clarification"].includes(
                      item.state ?? "",
                    ) && (
                      <button onClick={() => void cancel(item)}>
                        取消此请求
                      </button>
                    )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
