"use client";
import { useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type ShippingOrder = {
  id?: string;
  version?: number;
  lines?: {
    id?: string;
    product_id: string;
    quantity: string;
    shipped_quantity?: string;
  }[];
};
type Warehouse = {
  id?: string;
  name?: string;
  code?: string;
  active?: boolean;
};

export default function ShipmentEditor({
  api,
  order,
  close,
  saved,
}: {
  api: Api;
  order: ShippingOrder;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const warehouses = useQuery({
    queryKey: ["warehouses", "options"],
    queryFn: async () =>
      (await api("/warehouses?limit=100")) as { items: Warehouse[] },
  });
  const attempt = useRef<{ key: string; body: string } | null>(null);
  const [busy, setBusy] = useState(false),
    [frozen, setFrozen] = useState(false),
    [error, setError] = useState<unknown>();
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
            quantity: String(form.get(line.id ?? "") ?? "").trim(),
          }))
          .filter((line) => line.quantity !== "") ?? [];
      if (!lines.length) {
        setError(new Error("至少填写一行本次出库数量"));
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
      await api("/sales_orders/" + order.id + "/ship", {
        method: "POST",
        headers: { "Idempotency-Key": attempt.current.key },
        body: attempt.current.body,
      });
      await saved();
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
  const failure = error || warehouses.error;
  return (
    <div className="overlay">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label="登记销售出库"
      >
        <header>
          <h2>登记销售出库</h2>
          <button aria-label="关闭" disabled={busy} onClick={close}>
            <X size={18} />
          </button>
        </header>
        <form onSubmit={submit}>
          <p className="muted">
            填写本次实际发出的数量；留空的明细本次不出库。所有明细会一起校验，库存不足时整次操作不扣库存。
          </p>
          {failure ? (
            <p className="error" role="alert">
              {failure instanceof Error ? failure.message : String(failure)}
            </p>
          ) : null}
          {frozen && (
            <p className="notice compact" role="status">
              本次提交内容已锁定。结果暂未确认时，重试会处理同一次出库；关闭后请先刷新订单和出库记录。
            </p>
          )}
          <fieldset className="sales-fields" disabled={busy || frozen}>
            <label>
              出库仓库
              <select name="warehouse" aria-label="出库仓库" required>
                <option value="">选择仓库（前100条可见资料）</option>
                {warehouses.data?.items
                  .filter(
                    (row) =>
                      typeof row.id === "string" &&
                      row.id !== "***" &&
                      row.active !== false,
                  )
                  .map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name ?? row.code ?? row.id}
                    </option>
                  ))}
              </select>
            </label>
            {order.lines?.map((line, index) => (
              <label key={line.id}>
                明细 {index + 1} 本次出库数量
                <small className="muted">
                  商品 {line.product_id} · 计划 {line.quantity} · 已发{" "}
                  {line.shipped_quantity ?? "不可见"}
                </small>
                <input
                  aria-label={"明细 " + (index + 1) + " 本次出库数量"}
                  name={line.id}
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,4})?"
                />
              </label>
            ))}
          </fieldset>
          <button
            className="primary"
            disabled={
              busy || (!frozen && (warehouses.isPending || !!warehouses.error))
            }
          >
            {busy ? "出库中…" : frozen ? "重试相同出库请求" : "确认销售出库"}
          </button>
        </form>
      </section>
    </div>
  );
}
