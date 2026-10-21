"use client";
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Option = { id?: string; name?: string; sku?: string; active?: boolean };
type Line = {
  id?: string;
  product_id: string;
  quantity: string;
  unit_price?: string;
  amount?: string;
};
type Order = {
  id?: string;
  version?: number;
  number?: string;
  customer_id?: string;
  currency?: string;
  note?: string;
  status?: string;
  total?: string;
  lines?: Line[];
};
const statuses: Record<string, string> = {
  draft: "草稿",
  submitted: "待审批",
  approved: "已批准",
  cancelled: "已取消",
};
const visibleId = (value: unknown): value is string =>
  typeof value === "string" && value !== "***" && value.length > 0;
function Failure({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  ) : null;
}
async function get<T>(api: Api, path: string): Promise<T> {
  return (await api(path)) as T;
}

function DraftEditor({
  api,
  existing,
  close,
  saved,
}: {
  api: Api;
  existing?: Order;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const customers = useQuery({
    queryKey: ["customers", "options"],
    queryFn: () => get<{ items: Option[] }>(api, "/customers?limit=100"),
  });
  const products = useQuery({
    queryKey: ["products", "options"],
    queryFn: () => get<{ items: Option[] }>(api, "/products?limit=100"),
  });
  const [lines, setLines] = useState(
    existing?.lines?.map((line) => ({
      product_id: line.product_id,
      quantity: line.quantity,
      unit_price: line.unit_price ?? "",
    })) ?? [{ product_id: "", quantity: "", unit_price: "" }],
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  const choices = (rows: Option[] | undefined) =>
    rows?.filter((row) => visibleId(row.id) && row.active !== false) ?? [];
  const customerOptions = choices(customers.data?.items),
    productOptions = choices(products.data?.items);
  function edit(index: number, key: string, value: string) {
    setLines((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)),
    );
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    const data = new FormData(event.currentTarget);
    try {
      await api("/sales_orders" + (existing ? "/" + existing.id : ""), {
        method: existing ? "PATCH" : "POST",
        body: JSON.stringify({
          customer_id: data.get("customer"),
          currency: data.get("currency"),
          note: data.get("note"),
          lines,
          ...(existing ? { version: existing.version } : {}),
        }),
      });
      await saved();
      close();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="overlay">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={existing ? "编辑销售草稿" : "新建销售单"}
      >
        <header>
          <h2>{existing ? "编辑销售草稿" : "新建销售单"}</h2>
          <button aria-label="关闭" disabled={busy} onClick={close}>
            <X size={18} />
          </button>
        </header>
        <form onSubmit={submit}>
          <p className="muted">
            选项显示当前可访问的前100条资料。数量最多4位小数、单价最多2位小数，行金额须精确到分。
          </p>
          <Failure error={error || customers.error || products.error} />
          <fieldset disabled={busy} className="sales-fields">
            <label>
              客户
              <select
                aria-label="客户"
                name="customer"
                required
                defaultValue={existing?.customer_id ?? ""}
              >
                <option value="">选择客户</option>
                {existing?.customer_id &&
                  !customerOptions.some(
                    (row) => row.id === existing.customer_id,
                  ) && (
                    <option value={existing.customer_id}>
                      {existing.customer_id}（当前单据引用）
                    </option>
                  )}
                {customerOptions.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name ?? row.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              币种
              <input
                name="currency"
                required
                pattern="[A-Z]{3}"
                maxLength={3}
                placeholder="例如 CNY"
                defaultValue={existing?.currency ?? ""}
              />
            </label>
            <label>
              备注
              <input
                name="note"
                maxLength={2000}
                defaultValue={existing?.note ?? ""}
              />
            </label>
            {lines.map((row, index) => (
              <fieldset className="order-line" key={index}>
                <legend>销售明细 {index + 1}</legend>
                <label>
                  商品
                  <select
                    aria-label="商品"
                    required
                    value={row.product_id}
                    onChange={(event) =>
                      edit(index, "product_id", event.target.value)
                    }
                  >
                    <option value="">选择商品</option>
                    {row.product_id &&
                      !productOptions.some(
                        (product) => product.id === row.product_id,
                      ) && (
                        <option value={row.product_id}>
                          {row.product_id}（当前单据引用）
                        </option>
                      )}
                    {productOptions.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name ?? product.sku ?? product.id}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="form-grid">
                  <label>
                    数量
                    <input
                      required
                      inputMode="decimal"
                      pattern="[0-9]+(\.[0-9]{1,4})?"
                      value={row.quantity}
                      onChange={(event) =>
                        edit(index, "quantity", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    单价
                    <input
                      required
                      inputMode="decimal"
                      pattern="[0-9]+(\.[0-9]{1,2})?"
                      value={row.unit_price}
                      onChange={(event) =>
                        edit(index, "unit_price", event.target.value)
                      }
                    />
                  </label>
                </div>
                {lines.length > 1 && (
                  <button
                    type="button"
                    onClick={() =>
                      setLines((rows) => rows.filter((_, i) => i !== index))
                    }
                  >
                    移除此行
                  </button>
                )}
              </fieldset>
            ))}
            <button
              type="button"
              disabled={lines.length >= 100}
              onClick={() =>
                setLines((rows) => [
                  ...rows,
                  { product_id: "", quantity: "", unit_price: "" },
                ])
              }
            >
              <Plus size={16} />
              添加明细
            </button>
            <button
              className="primary"
              disabled={
                customers.isPending ||
                products.isPending ||
                !!customers.error ||
                !!products.error
              }
            >
              {busy ? "保存中…" : "保存销售草稿"}
            </button>
          </fieldset>
        </form>
      </section>
    </div>
  );
}

export default function SalesView({ api }: { api: Api }) {
  const qc = useQueryClient();
  const [after, setAfter] = useState<string>(),
    [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string>(),
    [editor, setEditor] = useState<Order | null>();
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [feedback, setFeedback] = useState("");
  const query = useQuery({
    queryKey: ["sales_orders", "list", status, after],
    queryFn: () =>
      get<{ items: Order[] }>(
        api,
        "/sales_orders?limit=50" +
          (status ? "&status=" + status : "") +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      ),
  });
  const detail = useQuery({
    queryKey: ["sales_orders", "detail", selected],
    queryFn: () => get<Order>(api, "/sales_orders/" + selected),
    enabled: !!selected,
  });
  const order = detail.error ? undefined : detail.data;
  const rows = query.error ? [] : (query.data?.items ?? []);
  const editable =
    order?.status === "draft" &&
    visibleId(order.customer_id) &&
    visibleId(order.currency) &&
    "note" in order &&
    order.note !== "***" &&
    Array.isArray(order.lines) &&
    order.lines.every(
      (line) =>
        visibleId(line.product_id) &&
        visibleId(line.unit_price) &&
        visibleId(line.quantity),
    );
  const actionable = visibleId(order?.id) && typeof order?.version === "number";
  async function saved() {
    await qc.invalidateQueries({ queryKey: ["sales_orders"] });
    setFeedback("销售草稿已保存");
  }
  async function transition(action: string) {
    if (!actionable || !order) return;
    setBusy(true);
    setError(undefined);
    setFeedback("");
    try {
      await api("/sales_orders/" + order.id + "/" + action, {
        method: "POST",
        body: JSON.stringify({ version: order.version }),
      });
      await qc.invalidateQueries({ queryKey: ["sales_orders"] });
      setFeedback(
        {
          submit: "已提交审批",
          approve: "销售单已批准",
          cancel: "销售单已取消",
        }[action] ?? "操作完成",
      );
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading sales-title">
        <div>
          <span className="eyebrow">SALES / ORDERS</span>
          <h1>销售订单</h1>
          <p className="muted">
            管理客户订单、明细与审批状态，保留每一次业务变更。
          </p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setEditor(null);
            setError(undefined);
            setFeedback("");
          }}
        >
          新建销售单
        </button>
      </div>
      <Failure error={query.error || detail.error || error} />
      <p role="status" className="muted">
        {feedback}
      </p>
      <section className="panel">
        <div className="panel-heading sales-list-heading">
          <h3>销售单列表</h3>
          <div className="actions-row">
            <label>
              销售状态
              <select
                aria-label="销售状态"
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  setAfter(undefined);
                }}
              >
                <option value="">全部可见状态</option>
                {Object.entries(statuses).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => {
                void query.refetch();
                if (selected) void detail.refetch();
              }}
            >
              刷新
            </button>
          </div>
        </div>
        {query.isPending ? (
          <p className="empty">加载销售单…</p>
        ) : !rows.length ? (
          <p className="empty">当前筛选下没有可查看的销售单</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>销售单号</th>
                  <th>状态</th>
                  <th>币种</th>
                  <th>金额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={row.id ?? index}>
                    <td>{row.number ?? "不可见"}</td>
                    <td>{statuses[row.status ?? ""] ?? "不可见"}</td>
                    <td>{row.currency ?? "不可见"}</td>
                    <td>{row.total ?? "不可见"}</td>
                    <td>
                      {visibleId(row.id) && (
                        <button
                          onClick={() => {
                            setSelected(row.id);
                            setError(undefined);
                            setFeedback("");
                          }}
                        >
                          查看销售单
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="panel-footer">
          <button disabled={!after} onClick={() => setAfter(undefined)}>
            返回首页
          </button>
          <button
            disabled={rows.length < 50 || !visibleId(rows.at(-1)?.id)}
            onClick={() => setAfter(rows.at(-1)?.id)}
          >
            下一页
          </button>
        </div>
      </section>
      {selected && detail.isPending && <p className="empty">加载销售明细…</p>}
      {order && (
        <section className="panel padded">
          <div className="panel-heading sales-detail-heading">
            <h2>{order.number ?? "销售单详情"}</h2>
            <button onClick={() => setSelected(undefined)}>关闭详情</button>
          </div>
          <p>
            状态：{statuses[order.status ?? ""] ?? "不可见"} · 金额：
            {order.total ?? "不可见"} {order.currency ?? ""}
          </p>
          <p className="muted">{order.note}</p>
          <div className="actions-row">
            {editable && actionable && (
              <button disabled={busy} onClick={() => setEditor(order)}>
                编辑销售草稿
              </button>
            )}
            {actionable && order.status === "draft" && (
              <button disabled={busy} onClick={() => void transition("submit")}>
                提交销售审批
              </button>
            )}
            {actionable && order.status === "submitted" && (
              <button
                className="primary"
                disabled={busy}
                onClick={() => void transition("approve")}
              >
                批准销售单
              </button>
            )}
            {actionable &&
              ["draft", "submitted", "approved"].includes(
                order.status ?? "",
              ) && (
                <button
                  disabled={busy}
                  onClick={() => void transition("cancel")}
                >
                  取消销售单
                </button>
              )}
          </div>
          <p className="muted">
            销售单创建人不能审批自己的订单。本阶段审批完成后不预留或扣减库存，出库功能开发中。
          </p>
          {Array.isArray(order.lines) ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>商品标识</th>
                    <th>数量</th>
                    <th>单价</th>
                    <th>行金额</th>
                  </tr>
                </thead>
                <tbody>
                  {order.lines.map((line, index) => (
                    <tr key={line.id ?? index}>
                      <td>{line.product_id}</td>
                      <td>{line.quantity}</td>
                      <td>{line.unit_price ?? "不可见"}</td>
                      <td>{line.amount ?? "不可见"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">明细字段不可见</p>
          )}
        </section>
      )}
      {editor !== undefined && (
        <DraftEditor
          api={api}
          existing={editor ?? undefined}
          close={() => setEditor(undefined)}
          saved={saved}
        />
      )}
    </>
  );
}
