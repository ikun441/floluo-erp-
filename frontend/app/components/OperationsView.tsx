"use client";
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Ref = { id?: string; name?: string; sku?: string };
type Operation = {
  id?: string;
  version?: number;
  state?: string;
  created_at?: string;
  expires_at?: string;
  missing_fields?: string[];
  preview_digest?: string;
  result_id?: string;
  result?: Record<string, unknown>;
  preview?: {
    number: string;
    currency: string;
    total: string;
    quantity: string;
    unit_price: string;
    product: Ref;
    supplier: Ref;
  };
};
const states: Record<string, string> = {
  collecting_missing: "待补充",
  awaiting_confirmation: "待确认",
  completed: "草稿已创建",
  cancelled: "已取消",
  expired: "已过期",
};
const fields: Record<string, string> = {
  product: "商品",
  supplier: "供应商",
  quantity: "数量",
  unit_price: "单价",
  currency: "币种",
};
async function call<T>(api: Api, path: string, init?: RequestInit) {
  return (await api(path, init)) as T;
}
function values(form: HTMLFormElement) {
  const data = new FormData(form);
  return Object.fromEntries(
    Object.keys(fields).flatMap((key) => {
      const v = String(data.get(key) ?? "").trim();
      return v ? [[key, v]] : [];
    }),
  );
}
function Failure({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  ) : null;
}
function Inputs({ api }: { api: Api }) {
  const products = useQuery({
    queryKey: ["products", "operation-options"],
    queryFn: () => call<{ items: Ref[] }>(api, "/products?limit=100"),
  });
  const suppliers = useQuery({
    queryKey: ["suppliers", "operation-options"],
    queryFn: () => call<{ items: Ref[] }>(api, "/suppliers?limit=100"),
  });
  return (
    <>
      <Failure error={products.error || suppliers.error} />
      {Object.entries(fields).map(([key, label]) => (
        <label key={key}>
          {label}
          {key === "product" || key === "supplier" ? (
            <select name={key} aria-label={label} defaultValue="">
              <option value="">请选择 / 保留原值</option>
              {(key === "product" ? products.data : suppliers.data)?.items
                .filter((r) => typeof r.id === "string" && r.id !== "***")
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name ?? r.sku ?? r.id}
                  </option>
                ))}
            </select>
          ) : (
            <input
              name={key}
              maxLength={key === "currency" ? 3 : 40}
              inputMode={key === "currency" ? "text" : "decimal"}
              placeholder={
                key === "currency"
                  ? "如 CNY，请明确填写"
                  : "仅填写要补充或修改的值"
              }
            />
          )}
        </label>
      ))}
    </>
  );
}
export default function OperationsView({ api }: { api: Api }) {
  const qc = useQueryClient();
  const [state, setState] = useState("");
  const [after, setAfter] = useState("");
  const [selected, setSelected] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const list = useQuery({
    queryKey: ["message_operations", state, after],
    queryFn: () =>
      call<{ items: Operation[] }>(
        api,
        "/message_operations?limit=50" +
          (state ? "&state=" + state : "") +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      ),
  });
  const detail = useQuery({
    queryKey: ["message_operation", selected],
    queryFn: () => call<Operation>(api, "/message_operations/" + selected),
    enabled: !!selected,
  });
  const row = detail.data;
  const rows = (list.data?.items ?? []).filter(
    (r) => typeof r.id === "string" && r.id !== "***",
  );
  const pending =
    row?.state === "collecting_missing" ||
    row?.state === "awaiting_confirmation";
  const editable = pending && typeof row?.version === "number";
  async function saved(result: Operation) {
    if (result.id && result.id !== "***") {
      setSelected(result.id);
      qc.setQueryData(["message_operation", result.id], result);
    }
    await qc.invalidateQueries({ queryKey: ["message_operations"] });
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    setBusy(true);
    setError(undefined);
    try {
      const result = await call<Operation>(api, "/message_operations", {
        method: "POST",
        body: JSON.stringify({ values: values(form) }),
      });
      await saved(result);
      setCreating(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!row?.id || busy) return;
    const form = event.currentTarget;
    setBusy(true);
    setError(undefined);
    try {
      await saved(
        await call<Operation>(api, "/message_operations/" + row.id, {
          method: "PATCH",
          body: JSON.stringify({ version: row.version, values: values(form) }),
        }),
      );
      form.reset();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function cancel(target: Operation | undefined = row) {
    if (!target?.id || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      await saved(
        await call<Operation>(
          api,
          "/message_operations/" + target.id + "/cancel",
          { method: "POST", body: JSON.stringify({ version: target.version }) },
        ),
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!row?.id || busy) return;
    const form = event.currentTarget;
    setBusy(true);
    setError(undefined);
    try {
      await saved(
        await call<Operation>(
          api,
          "/message_operations/" + row.id + "/confirm",
          {
            method: "POST",
            body: JSON.stringify({
              version: row.version,
              preview_digest: row.preview_digest,
              password: String(new FormData(form).get("password") ?? ""),
            }),
          },
        ),
      );
    } catch (e) {
      setError(e);
    } finally {
      const input = form.elements.namedItem("password");
      if (input instanceof HTMLInputElement) input.value = "";
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-heading operations-heading">
        <div>
          <span className="eyebrow">OPERATIONS / CONFIRMATION</span>
          <h1>操作工作台</h1>
          <p className="muted">
            先预览，再确认。消息请求和 Web
            请求共用业务校验；确认只创建采购草稿。
          </p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setCreating(!creating);
            setError(undefined);
          }}
          disabled={busy}
        >
          发起采购请求
        </button>
      </div>
      <Failure error={error || list.error} />
      {creating && (
        <section className="panel padded" aria-label="新建采购请求">
          <h2>新建采购请求</h2>
          <p className="muted">
            可先提交部分信息，稍后补充。选项为当前可见的前100条资料。
          </p>
          <form className="business-form" onSubmit={create}>
            <Inputs api={api} />
            <button className="primary" disabled={busy}>
              保存请求
            </button>
          </form>
        </section>
      )}
      <div className="operations-layout">
        <section className="panel" aria-label="我的请求">
          <div className="panel-heading">
            <h2>我的请求</h2>
            <label>
              请求状态
              <select
                aria-label="请求状态"
                value={state}
                onChange={(e) => {
                  setState(e.target.value);
                  setAfter("");
                  setSelected(undefined);
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
            <button onClick={() => void list.refetch()}>刷新列表</button>
          </div>
          {list.isPending ? (
            <p className="empty">正在加载请求…</p>
          ) : rows.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>请求 ID</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <code>{r.id}</code>
                      </td>
                      <td>{states[r.state ?? ""] ?? "状态不可见"}</td>
                      <td>
                        <button
                          onClick={() => {
                            setSelected(r.id);
                            setError(undefined);
                          }}
                        >
                          查看请求
                        </button>
                        {(r.state === "collecting_missing" ||
                          r.state === "awaiting_confirmation") &&
                          typeof r.version === "number" && (
                            <button
                              disabled={busy}
                              onClick={() => void cancel(r)}
                            >
                              取消请求
                            </button>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">没有当前可见的请求</p>
          )}
          <div className="panel-heading">
            <button disabled={!after} onClick={() => setAfter("")}>
              回到首页
            </button>
            <button
              disabled={rows.length < 50}
              onClick={() => setAfter(rows.at(-1)?.id ?? "")}
            >
              下一页
            </button>
          </div>
        </section>
        <section className="panel padded" aria-label="请求详情">
          <div className="panel-heading">
            <h2>请求详情</h2>
            {selected && (
              <button
                disabled={busy}
                onClick={() => {
                  setError(undefined);
                  void detail.refetch();
                }}
              >
                刷新预览
              </button>
            )}
          </div>
          <Failure error={detail.error} />
          {!selected ? (
            <p className="empty">选择一个请求查看当前授权预览</p>
          ) : detail.isPending ? (
            <p className="empty">正在校验预览…</p>
          ) : row && !detail.error ? (
            <>
              <p>
                <code>{row.id}</code>
              </p>
              <p>
                状态：<strong>{states[row.state ?? ""] ?? "不可见"}</strong>
              </p>
              {row.expires_at && (
                <p className="muted">
                  截止时间：{new Date(row.expires_at).toLocaleString("zh-CN")}
                </p>
              )}
              {row.missing_fields?.length ? (
                <p className="notice">
                  还需补充：
                  {row.missing_fields.map((f) => fields[f] ?? f).join("、")}
                </p>
              ) : null}
              {row.preview && (
                <div className="operation-preview">
                  <h3>采购草稿预览</h3>
                  <dl>
                    <dt>预留单号</dt>
                    <dd>{row.preview.number}</dd>
                    <dt>商品</dt>
                    <dd>
                      {row.preview.product.name ??
                        row.preview.product.sku ??
                        row.preview.product.id}
                    </dd>
                    <dt>供应商</dt>
                    <dd>
                      {row.preview.supplier.name ?? row.preview.supplier.id}
                    </dd>
                    <dt>数量</dt>
                    <dd>{row.preview.quantity}</dd>
                    <dt>单价</dt>
                    <dd>
                      {row.preview.unit_price} {row.preview.currency}
                    </dd>
                    <dt>合计</dt>
                    <dd>
                      <strong>
                        {row.preview.total} {row.preview.currency}
                      </strong>
                    </dd>
                  </dl>
                  <p className="muted">
                    确认后仍需按业务规则提交、审批和入库。
                  </p>
                </div>
              )}
              {editable && (
                <>
                  <details>
                    <summary>补充或修改参数</summary>
                    <form
                      className="business-form"
                      aria-label="补充请求"
                      onSubmit={update}
                    >
                      <Inputs api={api} />
                      <button disabled={busy}>保存补充信息</button>
                    </form>
                  </details>
                  <button disabled={busy} onClick={() => void cancel()}>
                    取消请求
                  </button>
                </>
              )}
              {editable &&
                row.state === "awaiting_confirmation" &&
                row.preview &&
                row.preview_digest && (
                  <form
                    className="business-form"
                    aria-label="确认请求"
                    onSubmit={confirm}
                  >
                    <label>
                      当前 ERP 密码
                      <input
                        type="password"
                        name="password"
                        autoComplete="current-password"
                        required
                        maxLength={1024}
                      />
                    </label>
                    <button className="primary" disabled={busy}>
                      确认创建采购草稿
                    </button>
                  </form>
                )}
              {row.state === "completed" && (
                <div className="notice">
                  <h3>采购草稿已创建</h3>
                  {row.result ? (
                    <p>
                      单号：
                      {String(
                        row.result.number ?? row.result.id ?? "当前字段不可见",
                      )}
                      ；状态：{String(row.result.status ?? "不可见")}
                    </p>
                  ) : (
                    <p>详情按当前采购权限展示，请在采购订单页面查看。</p>
                  )}
                </div>
              )}
              {(row.state === "cancelled" || row.state === "expired") && (
                <p className="muted">
                  该请求不会创建订单，如需操作请重新发起。
                </p>
              )}
            </>
          ) : null}
        </section>
      </div>
    </>
  );
}
