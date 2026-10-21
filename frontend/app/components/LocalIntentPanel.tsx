"use client";
import { useState, type FormEvent } from "react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Parsed = {
  intent: {
    operation: "query" | "create";
    resource: "inventory" | "purchase_orders";
    arguments: Record<string, string>;
    references: Record<string, string>;
    parser_source: "command" | "local_rule";
  };
  missing: string[];
};
type QueryResult = { resource: string; items: Record<string, unknown>[] };
const labels: Record<string, string> = {
  product: "商品",
  supplier: "供应商",
  quantity: "数量",
  unit: "单位",
  unit_price: "单价",
  currency: "币种",
  query: "商品名称",
  number: "采购单号",
  id: "记录 ID",
  warehouse_id: "仓库 ID",
  product_id: "商品 ID",
  version: "版本",
  owner_id: "归属用户",
  department_id: "部门",
  total: "合计",
  status: "状态",
  supplier_id: "供应商 ID",
  created_at: "创建时间",
  updated_at: "更新时间",
  lines: "商品明细",
  note: "备注",
};
function display(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} 项`;
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return "详情";
  return String(value);
}
export default function LocalIntentPanel({
  api,
  onCreated,
}: {
  api: Api;
  onCreated: (row: { id?: string }) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<Parsed>();
  const [result, setResult] = useState<QueryResult>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function parse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(undefined);
    setParsed(undefined);
    setResult(undefined);
    try {
      setParsed(
        (await api("/intents/parse", {
          method: "POST",
          body: JSON.stringify({ text }),
        })) as Parsed,
      );
    } catch {
      setError(
        "未能识别这条描述，请使用下方格式或 /erp 固定命令。没有创建请求，也没有调用 AI。",
      );
    } finally {
      setBusy(false);
    }
  }
  async function run() {
    if (!parsed || busy) return;
    setBusy(true);
    setError(undefined);
    setResult(undefined);
    try {
      const query = parsed.intent.operation === "query";
      const response = await api(
        query ? "/intents/query" : "/intents/requests",
        {
          method: "POST",
          body: JSON.stringify({ text }),
        },
      );
      if (query) setResult(response as QueryResult);
      else {
        await onCreated(response as { id?: string });
        setParsed(undefined);
        setText("");
      }
    } catch (e) {
      setError(
        (e instanceof Error ? e.message : "操作失败") +
          "。请核对当前权限、商品单位和资料，再重试。",
      );
    } finally {
      setBusy(false);
    }
  }
  const columns = Array.from(
    new Set(result?.items.flatMap((row) => Object.keys(row)) ?? []),
  );
  return (
    <section className="panel padded local-intent" aria-label="离线指令助手">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">LOCAL / OFFLINE</span>
          <h2>用一句话开始</h2>
        </div>
        <span className="badge">本地规则 · 无需 AI</span>
      </div>
      <p className="muted" id="local-intent-help">
        支持单商品库存查询和采购描述。先查看识别结果，再执行查询或保存待确认请求。
      </p>
      <form onSubmit={parse}>
        <label htmlFor="local-intent-text">业务描述</label>
        <textarea
          id="local-intent-text"
          rows={3}
          maxLength={4096}
          required
          aria-describedby="local-intent-help"
          value={text}
          disabled={busy}
          placeholder={
            "例如：查询一下鼠标还有多少库存。\n登记采购20个鼠标，每个35元。"
          }
          onChange={(e) => {
            setText(e.target.value);
            setParsed(undefined);
            setResult(undefined);
            setError(undefined);
          }}
        />
        <div className="local-intent-actions">
          <button className="primary" disabled={busy || !text.trim()}>
            识别描述
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setText("");
              setParsed(undefined);
              setResult(undefined);
              setError(undefined);
            }}
          >
            清空
          </button>
        </div>
      </form>
      <details className="local-intent-guide">
        <summary>支持的表达与填写规则</summary>
        <p>查询：查询一下鼠标还有多少库存。也支持「查询采购订单」。</p>
        <p>采购：登记采购20个鼠标，每个35元，供应商=供应商编码，币种=CNY。</p>
        <p className="muted">
          含空格或连接词的名称可用双引号包围。数量和金额使用阿拉伯数字；单位须与商品资料一致，不做换算。「元」不会自动补成
          CNY，缺失信息可稍后补齐。
        </p>
      </details>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {busy ? (
        <p className="muted" role="status">
          正在处理…
        </p>
      ) : null}
      {parsed ? (
        <div className="local-intent-result" aria-live="polite">
          <h3>
            识别结果：
            {parsed.intent.operation === "create"
              ? "发起采购请求"
              : parsed.intent.resource === "inventory"
                ? "查询库存"
                : "查询采购订单"}
          </h3>
          <p className="muted">
            来源：
            {parsed.intent.parser_source === "command"
              ? "固定命令"
              : "本地规则"}
          </p>
          <dl>
            {Object.entries({
              ...parsed.intent.references,
              ...parsed.intent.arguments,
            }).map(([key, value]) => (
              <div key={key}>
                <dt>{labels[key] ?? key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {parsed.missing.length ? (
            <p>
              还需补充：
              {parsed.missing.map((key) => labels[key] ?? key).join("、")}
            </p>
          ) : null}
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => void run()}
          >
            {parsed.intent.operation === "query"
              ? "执行授权查询"
              : "生成待确认请求"}
          </button>
          <p className="muted">
            {parsed.intent.operation === "query"
              ? "仅返回当前权限允许的数据，最多20条。"
              : "保存后仍须在详情预览并复核密码，才能创建采购草稿。"}
          </p>
        </div>
      ) : null}
      {result ? (
        <div aria-live="polite">
          <h3>查询结果</h3>
          {result.items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {columns.map((key) => (
                      <th key={key}>{labels[key] ?? key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((row, index) => (
                    <tr key={index}>
                      {columns.map((key) => (
                        <td key={key}>{display(row[key])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">当前授权范围内没有匹配记录。</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
