"use client";
import { useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Row = Record<string, unknown>;
type Line = {
  id: string;
  product_id: string;
  quantity: string;
  received_quantity: string;
  unit_price?: string;
  amount?: string;
};
type Order = {
  id: string;
  version: number;
  number?: string;
  supplier_id?: string;
  currency?: string;
  note?: string;
  status?: string;
  total?: string;
  lines?: Line[];
};
const statuses: Record<string, string> = {
  draft: "草稿",
  submitted: "待审批",
  approved: "待入库",
  partially_received: "部分入库",
  received: "已入库",
  cancelled: "已取消",
};
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
function useOptions(api: Api, resource: string) {
  return useQuery({
    queryKey: [resource, "options"],
    queryFn: () => call<{ items: Row[] }>(api, "/" + resource + "?limit=100"),
  });
}
function options(rows: Row[] | undefined) {
  return rows?.filter((r) => typeof r.id === "string" && r.id !== "***") ?? [];
}
function title(row: Row) {
  return String(row.name ?? row.sku ?? row.code ?? row.id);
}
function Modal({
  title: heading,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="overlay">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={heading}
      >
        <header>
          <h2>{heading}</h2>
          <button aria-label="关闭" onClick={close}>
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
function DraftEditor({
  api,
  existing,
  done,
}: {
  api: Api;
  existing?: Order;
  done: () => void;
}) {
  const suppliers = useOptions(api, "suppliers"),
    products = useOptions(api, "products");
  const [lines, setLines] = useState(
    existing?.lines?.map((line) => ({
      product_id: line.product_id,
      quantity: line.quantity,
      unit_price: line.unit_price ?? "",
    })) ?? [{ product_id: "", quantity: "", unit_price: "" }],
  );
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  function line(index: number, key: string, value: string) {
    setLines(
      lines.map((row, i) => (i === index ? { ...row, [key]: value } : row)),
    );
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    const form = new FormData(event.currentTarget);
    try {
      await api("/purchase_orders" + (existing ? "/" + existing.id : ""), {
        method: existing ? "PATCH" : "POST",
        body: JSON.stringify({
          supplier_id: form.get("supplier"),
          currency: form.get("currency"),
          note: form.get("note"),
          lines,
          ...(existing ? { version: existing.version } : {}),
        }),
      });
      done();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={existing ? "编辑采购草稿" : "新建采购草稿"} close={done}>
      <form onSubmit={submit}>
        <p className="muted">
          选择可访问的资料。数量与金额保留精确小数，金额不自动四舍五入。
        </p>
        <Failure error={suppliers.error || products.error || error} />
        <label>
          供应商
          <select
            aria-label="供应商"
            name="supplier"
            required
            defaultValue={existing?.supplier_id ?? ""}
          >
            <option value="">选择供应商</option>
            {options(suppliers.data?.items).map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {title(row)}
              </option>
            ))}
          </select>
        </label>
        <label>
          币种
          <input
            name="currency"
            placeholder="例如 CNY"
            pattern="[A-Z]{3}"
            maxLength={3}
            defaultValue={existing?.currency ?? ""}
            required
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
        {lines.map((row, i) => (
          <fieldset className="order-line" key={i}>
            <legend>采购明细 {i + 1}</legend>
            <label>
              商品
              <select
                required
                aria-label="商品"
                value={row.product_id}
                onChange={(event) => line(i, "product_id", event.target.value)}
              >
                <option value="">选择商品</option>
                {options(products.data?.items).map((product) => (
                  <option key={String(product.id)} value={String(product.id)}>
                    {title(product)}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-grid">
              <label>
                数量
                <input
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,4})?"
                  required
                  value={row.quantity}
                  onChange={(event) => line(i, "quantity", event.target.value)}
                />
              </label>
              <label>
                单价
                <input
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,2})?"
                  required
                  value={row.unit_price}
                  onChange={(event) =>
                    line(i, "unit_price", event.target.value)
                  }
                />
              </label>
            </div>
            {lines.length > 1 && (
              <button
                type="button"
                onClick={() => setLines(lines.filter((_, j) => i !== j))}
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
            setLines([
              ...lines,
              { product_id: "", quantity: "", unit_price: "" },
            ])
          }
        >
          <Plus size={16} />
          添加明细
        </button>
        <button
          className="primary"
          disabled={busy || suppliers.isPending || products.isPending}
        >
          {busy ? "保存中…" : "保存草稿"}
        </button>
      </form>
    </Modal>
  );
}
function ReceiptEditor({
  api,
  order,
  done,
}: {
  api: Api;
  order: Order;
  done: () => void;
}) {
  const warehouses = useOptions(api, "warehouses");
  const attempt = useRef<{ key: string; body: string } | null>(null);
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [frozen, setFrozen] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    if (!attempt.current) {
      const form = new FormData(event.currentTarget);
      const lines =
        order.lines
          ?.map((line) => ({
            line_id: line.id,
            quantity: String(form.get(line.id) ?? "").trim(),
          }))
          .filter((line) => line.quantity !== "") ?? [];
      if (!lines.length) {
        setError(new Error("至少填写一行本次收货数量"));
        setBusy(false);
        return;
      }
      attempt.current = {
        key: crypto.randomUUID(),
        body: JSON.stringify({
          version: order.version,
          warehouse_id: form.get("warehouse"),
          lines,
        }),
      };
      setFrozen(true);
    }
    try {
      await api("/purchase_orders/" + order.id + "/receive", {
        method: "POST",
        headers: { "Idempotency-Key": attempt.current.key },
        body: attempt.current.body,
      });
      done();
    } catch (error) {
      setError(error);
      if (
        error &&
        typeof error === "object" &&
        "status" in error &&
        typeof error.status === "number" &&
        error.status >= 400 &&
        error.status < 500
      ) {
        attempt.current = null;
        setFrozen(false);
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="确认采购入库" close={done}>
      <form onSubmit={submit}>
        <p className="muted">
          填写本次实际收到的数量；留空的明细本次不入库。网络结果不明时重试会使用同一请求。
        </p>
        <Failure error={warehouses.error || error} />
        <label>
          入库仓库
          <select
            aria-label="入库仓库"
            name="warehouse"
            required
            disabled={frozen}
          >
            <option value="">选择仓库</option>
            {options(warehouses.data?.items).map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {title(row)}
              </option>
            ))}
          </select>
        </label>
        {order.lines?.map((line, index) => (
          <label key={line.id}>
            明细 {index + 1} 本次收货数量
            <small className="muted">
              计划 {line.quantity} · 已收 {line.received_quantity}
            </small>
            <input
              name={line.id}
              inputMode="decimal"
              pattern="[0-9]+(\.[0-9]{1,4})?"
              disabled={frozen}
            />
          </label>
        ))}
        <button className="primary" disabled={busy}>
          {busy ? "入库中…" : frozen ? "重试相同入库请求" : "确认入库"}
        </button>
      </form>
    </Modal>
  );
}
export default function ProcurementView({ api }: { api: Api }) {
  const qc = useQueryClient();
  const [after, setAfter] = useState<string>(),
    [selected, setSelected] = useState<string>(),
    [editor, setEditor] = useState<"draft" | "receipt">(),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const query = useQuery({
    queryKey: ["purchase_orders", "list", after],
    queryFn: () =>
      call<{ items: Order[] }>(
        api,
        "/purchase_orders?limit=50" +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      ),
  });
  const detail = useQuery({
    queryKey: ["purchase_orders", selected],
    queryFn: () => call<Order>(api, "/purchase_orders/" + selected),
    enabled: !!selected,
  });
  const order = detail.data;
  async function done() {
    setEditor(undefined);
    await qc.invalidateQueries({
      predicate: (query) =>
        [
          "purchase_orders",
          "purchase_receipts",
          "inventory_balances",
          "stock_movements",
        ].includes(String(query.queryKey[0])),
    });
  }
  async function transition(action: string) {
    if (!order) return;
    setBusy(true);
    setError(undefined);
    try {
      await api("/purchase_orders/" + order.id + "/" + action, {
        method: "POST",
        body: JSON.stringify({ version: order.version }),
      });
      await done();
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  const editable =
    order?.status === "draft" &&
    order.supplier_id &&
    order.currency &&
    Array.isArray(order.lines) &&
    order.lines.every(
      (line) =>
        typeof line.unit_price === "string" && line.unit_price !== "***",
    );
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">PROCUREMENT / OPERATIONS</span>
          <h1>采购订单</h1>
          <p className="muted">草稿、审批与实际入库，全程留下业务记录。</p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setSelected(undefined);
            setEditor("draft");
          }}
        >
          新建采购单
        </button>
      </div>
      <Failure error={query.error || detail.error || error} />
      <section className="panel">
        <div className="panel-heading">
          <h3>采购单列表</h3>
          <button onClick={() => void query.refetch()}>刷新</button>
        </div>
        {query.isPending ? (
          <p className="empty">加载采购单…</p>
        ) : !query.data?.items.length ? (
          <p className="empty">当前没有可查看的采购单</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>采购单号</th>
                  <th>状态</th>
                  <th>币种</th>
                  <th>金额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((row, index) => (
                  <tr key={row.id ?? index}>
                    <td>{row.number ?? "—"}</td>
                    <td>{statuses[row.status ?? ""] ?? "—"}</td>
                    <td>{row.currency ?? "—"}</td>
                    <td>{row.total ?? "—"}</td>
                    <td>
                      {typeof row.id === "string" && row.id !== "***" && (
                        <button
                          onClick={() => {
                            setSelected(row.id);
                            setError(undefined);
                          }}
                        >
                          查看采购单
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
          <button onClick={() => setAfter(undefined)}>返回首页</button>
          <button
            disabled={
              (query.data?.items.length ?? 0) < 50 ||
              !query.data?.items.at(-1)?.id
            }
            onClick={() => setAfter(query.data?.items.at(-1)?.id)}
          >
            下一页
          </button>
        </div>
      </section>
      {selected && order && (
        <section className="panel padded">
          <h2>{order.number ?? "采购单详情"}</h2>
          <p>
            状态：{statuses[order.status ?? ""] ?? "不可见"} · 金额：
            {order.total ?? "不可见"} {order.currency ?? ""}
          </p>
          <p>{order.note}</p>
          <div className="actions-row">
            {editable && (
              <button onClick={() => setEditor("draft")}>编辑草稿</button>
            )}
            {order.status === "draft" && (
              <button disabled={busy} onClick={() => void transition("submit")}>
                提交审批
              </button>
            )}
            {order.status === "submitted" && (
              <button
                disabled={busy}
                onClick={() => void transition("approve")}
              >
                批准采购单
              </button>
            )}
            {["draft", "submitted", "approved"].includes(
              order.status ?? "",
            ) && (
              <button disabled={busy} onClick={() => void transition("cancel")}>
                取消采购单
              </button>
            )}
            {["approved", "partially_received"].includes(order.status ?? "") &&
              Array.isArray(order.lines) && (
                <button
                  disabled={busy}
                  className="primary"
                  onClick={() => setEditor("receipt")}
                >
                  登记入库
                </button>
              )}
          </div>
          {Array.isArray(order.lines) && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>商品标识</th>
                    <th>计划数量</th>
                    <th>已收数量</th>
                    <th>单价</th>
                    <th>行金额</th>
                  </tr>
                </thead>
                <tbody>
                  {order.lines.map((line) => (
                    <tr key={line.id}>
                      <td>{line.product_id}</td>
                      <td>{line.quantity}</td>
                      <td>{line.received_quantity}</td>
                      <td>{line.unit_price ?? "不可见"}</td>
                      <td>{line.amount ?? "不可见"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {editor === "draft" && (
        <DraftEditor
          api={api}
          existing={selected ? order : undefined}
          done={() => void done()}
        />
      )}
      {editor === "receipt" && order && (
        <ReceiptEditor api={api} order={order} done={() => void done()} />
      )}
    </>
  );
}
export function StockView({ api }: { api: Api }) {
  const [resource, setResource] = useState("inventory_balances"),
    [after, setAfter] = useState<string>();
  const query = useQuery({
    queryKey: [resource, "list", after],
    queryFn: () =>
      call<{ items: Row[] }>(
        api,
        "/" +
          resource +
          "?limit=50" +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      ),
  });
  const visibleFields = new Set(
    query.data?.items.flatMap((row) => Object.keys(row)) ?? [],
  );
  const preferred: Record<string, string[]> = {
    inventory_balances: [
      "warehouse_id",
      "product_id",
      "quantity",
      "version",
      "id",
      "owner_id",
      "department_id",
    ],
    stock_movements: [
      "kind",
      "quantity",
      "warehouse_id",
      "product_id",
      "receipt_line_id",
      "shipment_line_id",
      "id",
      "version",
      "owner_id",
      "department_id",
    ],
    purchase_receipts: [
      "number",
      "warehouse_id",
      "order_id",
      "lines",
      "id",
      "version",
      "owner_id",
      "department_id",
    ],
    sales_shipments: [
      "number",
      "warehouse_id",
      "order_id",
      "created_at",
      "lines",
      "id",
      "version",
      "owner_id",
      "department_id",
    ],
  };
  const columns = [
    ...(preferred[resource] ?? []).filter((field) => visibleFields.has(field)),
    ...Array.from(visibleFields).filter(
      (field) => !(preferred[resource] ?? []).includes(field),
    ),
  ];
  const labels: Record<string, string> = {
    inventory_balances: "库存余额",
    stock_movements: "库存流水",
    purchase_receipts: "采购入库单",
    sales_shipments: "销售出库单",
    id: "标识",
    version: "版本",
    quantity: "数量",
    warehouse_id: "仓库",
    product_id: "商品",
    owner_id: "所属用户",
    department_id: "部门",
    kind: "类型",
    receipt_line_id: "入库明细",
    shipment_line_id: "出库明细",
    created_at: "创建时间",
    number: "业务单号",
    order_id: "来源订单",
    lines: "明细",
  };
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">INVENTORY / TRACEABILITY</span>
          <h1>库存与出入库</h1>
          <p className="muted">
            库存由采购入库增加、销售出库扣减；流水数量为正数，方向由类型区分。
          </p>
        </div>
      </div>
      <div className="actions-row">
        {[
          "inventory_balances",
          "stock_movements",
          "purchase_receipts",
          "sales_shipments",
        ].map((key) => (
          <button
            key={key}
            aria-pressed={key === resource}
            onClick={() => {
              setResource(key);
              setAfter(undefined);
            }}
          >
            {labels[key]}
          </button>
        ))}
      </div>
      <Failure error={query.error} />
      <section className="panel padded">
        <h2>{labels[resource]}</h2>
        {query.isPending ? (
          <p>加载中…</p>
        ) : !query.data?.items.length ? (
          <p className="empty">当前没有可查看的记录</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((key) => (
                    <th key={key}>
                      {key === "quantity" && resource === "stock_movements"
                        ? "变动数量（绝对值）"
                        : (labels[key] ?? key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((row, index) => (
                  <tr key={String(row.id ?? index)}>
                    {columns.map((key) => (
                      <td key={key}>
                        {key === "kind"
                          ? ({
                              purchase_receipt: "采购入库（增加）",
                              sales_shipment: "销售出库（扣减）",
                            }[String(row[key])] ?? String(row[key] ?? "不可见"))
                          : typeof row[key] === "object"
                            ? JSON.stringify(row[key])
                            : String(row[key] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="panel-footer">
          <button onClick={() => setAfter(undefined)}>返回首页</button>
          <button
            disabled={
              (query.data?.items.length ?? 0) < 50 ||
              typeof query.data?.items.at(-1)?.id !== "string"
            }
            onClick={() => setAfter(String(query.data?.items.at(-1)?.id))}
          >
            下一页
          </button>
        </div>
      </section>
    </>
  );
}
export function BusinessConfiguration({ api }: { api: Api }) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["system_configuration"],
    queryFn: () => call<Row>(api, "/system_configuration"),
  });
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const values = query.data;
  const visible =
    values &&
    Array.isArray(values.supported_currencies) &&
    typeof values.require_separate_approver === "boolean" &&
    ["unconfigured", "no_tax"].includes(String(values.tax_mode));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!values) return;
    setBusy(true);
    setError(undefined);
    const form = new FormData(event.currentTarget);
    const next: Row = {
      supported_currencies: String(form.get("currencies"))
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      tax_mode: form.get("tax"),
      require_separate_approver: form.get("separate") === "on",
    };
    const changed = Object.fromEntries(
      Object.entries(next).filter(
        ([key, value]) => JSON.stringify(value) !== JSON.stringify(values[key]),
      ),
    );
    try {
      await api("/system_configuration", {
        method: "PATCH",
        body: JSON.stringify({ version: values.version, values: changed }),
      });
      await qc.invalidateQueries({ queryKey: ["system_configuration"] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">BUSINESS / CONFIGURATION</span>
          <h1>业务规则配置</h1>
          <p className="muted">
            配置采购与销售共用的币种和税模式，配置完成后才能提交审批。
          </p>
        </div>
      </div>
      <Failure error={query.error || error} />
      {query.isPending ? (
        <p>加载配置…</p>
      ) : visible ? (
        <section className="panel padded">
          <form
            className="business-form"
            onSubmit={submit}
            key={String(values.version)}
          >
            <label>
              支持币种（逗号分隔）
              <input
                name="currencies"
                pattern="[A-Z, ]*"
                placeholder="例如 CNY"
                defaultValue={(values.supported_currencies as string[]).join(
                  ",",
                )}
              />
            </label>
            <label>
              税模式
              <select
                aria-label="税模式"
                name="tax"
                defaultValue={String(values.tax_mode)}
              >
                <option value="unconfigured">未配置（阻止提交）</option>
                <option value="no_tax">无税模式（采购与销售不计算税额）</option>
              </select>
            </label>
            <label className="business-check">
              <input
                type="checkbox"
                name="separate"
                defaultChecked={Boolean(values.require_separate_approver)}
              />
              采购审批人必须与采购单创建人不同（销售始终独立审批）
            </label>
            <button className="primary" disabled={busy}>
              {busy ? "保存中…" : "保存业务规则"}
            </button>
          </form>
        </section>
      ) : (
        !query.error && <p className="empty">当前权限不足以编辑完整业务配置</p>
      )}
    </>
  );
}
