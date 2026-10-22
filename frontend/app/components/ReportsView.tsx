"use client";
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, RefreshCw, BarChart3 } from "lucide-react";

type Api = (path: string, init?: RequestInit) => Promise<unknown>;
type Kind = "inventory" | "movements" | "purchases" | "sales";
type Result = {
  items: Record<string, string | number>[];
  columns: string[];
  source_rows: number;
  policy_revision: number;
};
const reports: Record<Kind, { title: string; description: string }> = {
  inventory: {
    title: "当前库存",
    description: "当前可读的仓库与商品余额，保留原始单位，不跨商品合计。",
  },
  movements: {
    title: "出入库汇总",
    description:
      "采购增加、销售扣减分别统计，数量保持正数。此处是发生量，不是当前结存。",
  },
  purchases: {
    title: "采购汇总",
    description: "按业务状态和币种汇总采购订单；订单金额不代表已付款金额。",
  },
  sales: {
    title: "销售汇总",
    description: "按业务状态和币种汇总销售订单；订单金额不代表回款或确认收入。",
  },
};
const labels: Record<string, string> = {
  warehouse_name: "仓库",
  warehouse_code: "仓库编码",
  product_name: "商品",
  sku: "商品编码",
  unit: "单位",
  quantity: "数量",
  kind: "方向",
  status: "状态",
  currency: "币种",
  source_rows: "来源记录数",
  amount: "订单金额",
};
const statuses: Record<string, string> = {
  draft: "草稿",
  submitted: "待审批",
  approved: "已批准",
  cancelled: "已取消",
  partially_received: "部分入库",
  received: "已入库",
  partially_shipped: "部分出库",
  shipped: "已出库",
};
const failureMessages: Record<string, string> = {
  report_permission_denied:
    "当前账号没有完整的读取、报表或导出权限，请联系管理员授权。",
  report_source_limit: "记录超过 10000 条，请缩小筛选范围。",
  report_group_limit: "分组超过 200 组，请缩小筛选范围。",
  report_query_timeout: "计算超时，请缩小筛选范围后重试。",
  authentication_required: "登录已失效，请重新登录。",
};
function value(key: string, data: string | number) {
  if (key === "status") return statuses[data] ?? String(data);
  if (key === "kind")
    return data === "purchase_receipt"
      ? "采购入库（增加）"
      : "销售出库（扣减）";
  return String(data);
}
function Report({ api, name }: { api: Api; name: Kind }) {
  const orders = name === "sales" || name === "purchases";
  const [params, setParams] = useState("");
  const [downloadError, setDownloadError] = useState<string>();
  const [downloading, setDownloading] = useState(false);
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["reports", name, params],
    queryFn: () => api(`/reports/${name}${params}`) as Promise<Result>,
  });
  // Do not leave previously authorized values visible after a failed revalidation.
  const data = !query.isError && !query.isFetching ? query.data : undefined;
  const columns =
    data?.columns.filter(
      (key) => key !== "product_id" && key !== "warehouse_id",
    ) ?? [];
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const search = new URLSearchParams();
    new FormData(event.currentTarget).forEach((item, key) => {
      if (String(item).trim()) search.set(key, String(item).trim());
    });
    setParams(search.size ? "?" + search.toString() : "");
    setDownloadError(undefined);
    setNotice("");
  }
  async function download() {
    setDownloading(true);
    setDownloadError(undefined);
    setNotice("");
    try {
      const response = await fetch(`/api/v1/reports/${name}/export${params}`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(
          failureMessages[error.detail] ?? "导出失败，请刷新后重试。",
        );
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${name}.csv`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("CSV 已下载，内容按导出时的当前权限重新计算。");
    } catch (error) {
      setDownloadError(
        error instanceof Error ? error.message : "下载失败，请重试。",
      );
      // A denied export may accompany a revoked read permission: revalidate the table too.
      void query.refetch();
    } finally {
      setDownloading(false);
    }
  }
  return (
    <>
      <section className="panel report-filters">
        <div className="panel-heading">
          <div>
            <h2>{reports[name].title}</h2>
            <p className="muted">{reports[name].description}</p>
          </div>
        </div>
        <form onSubmit={apply}>
          {orders ? (
            <>
              <label>
                订单指标
                <select name="metric" defaultValue="count">
                  <option value="count">订单数量</option>
                  <option value="amount">订单数量与金额</option>
                </select>
              </label>
              <label>
                订单状态
                <select name="status" defaultValue="">
                  <option value="">全部合格状态</option>
                  {Object.entries(statuses)
                    .filter(([key]) =>
                      name === "sales"
                        ? !["received", "partially_received"].includes(key)
                        : !["shipped", "partially_shipped"].includes(key),
                    )
                    .map(([key, text]) => (
                      <option key={key} value={key}>
                        {text}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                币种
                <input
                  name="currency"
                  placeholder="例如 CNY"
                  maxLength={3}
                  pattern="[A-Z]{3}"
                />
              </label>
            </>
          ) : (
            <>
              <label>
                仓库 ID
                <input
                  name="warehouse_id"
                  placeholder="全部合格仓库"
                  maxLength={80}
                />
              </label>
              <label>
                商品 ID
                <input
                  name="product_id"
                  placeholder="全部合格商品"
                  maxLength={80}
                />
              </label>
              {name === "movements" && (
                <label>
                  出入库方向
                  <select name="kind" defaultValue="">
                    <option value="">全部合格方向</option>
                    <option value="purchase_receipt">采购入库（增加）</option>
                    <option value="sales_shipment">销售出库（扣减）</option>
                  </select>
                </label>
              )}
            </>
          )}
          <button
            className="primary"
            type="submit"
            disabled={query.isFetching || downloading}
          >
            应用筛选
          </button>
          <button
            type="button"
            onClick={() => {
              void query.refetch();
              setNotice("");
            }}
            disabled={query.isFetching || downloading}
          >
            <RefreshCw size={15} />
            刷新报表
          </button>
        </form>
        <p className="report-scope">
          仅统计当前权限下字段完整可读的记录；脱敏或隐藏字段不参与对应统计。空结果不代表企业没有业务记录。最多
          10000 条来源记录、200 组，超限会明确提示。
        </p>
      </section>
      {query.error && (
        <p className="error" role="alert">
          {query.error instanceof Error ? query.error.message : "报表加载失败"}
        </p>
      )}
      {downloadError && (
        <p className="error" role="alert">
          {downloadError}
        </p>
      )}
      {notice && (
        <p role="status" className="report-notice">
          {notice}
        </p>
      )}
      {query.isFetching ? (
        <p className="empty" role="status">
          正在校验权限并计算报表…
        </p>
      ) : data ? (
        <>
          <div className="report-cards">
            <article>
              <span>合格来源记录</span>
              <strong>{data.source_rows}</strong>
              <small>已应用数据范围及字段约束</small>
            </article>
            <article>
              <span>完整汇总分组</span>
              <strong>{data.items.length}</strong>
              <small>当前筛选下的全部合格分组</small>
            </article>
            <article>
              <span>当前策略版本</span>
              <strong>#{data.policy_revision}</strong>
              <small>统计和下载均重新授权</small>
            </article>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <h2>报表明细</h2>
              <button
                onClick={() => void download()}
                disabled={downloading || !data.items.length}
              >
                <Download size={15} />
                {downloading ? "正在导出…" : "导出 CSV"}
              </button>
            </div>
            {!data.items.length ? (
              <p className="empty">当前筛选与授权范围内没有合格记录。</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">
                    {reports[name].title}，当前授权范围内的完整汇总
                  </caption>
                  <thead>
                    <tr>
                      {columns.map((key) => (
                        <th key={key} scope="col">
                          {labels[key] ?? key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((row, index) => (
                      <tr key={index}>
                        {columns.map((key) => (
                          <td key={key}>{value(key, row[key])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {orders && data.items.length > 0 && (
            <section className="panel report-distribution">
              <div className="panel-heading">
                <h2>订单数量分布</h2>
                <span className="muted">条形长度仅比较订单数</span>
              </div>
              <ul>
                {data.items.map((row, index) => (
                  <li key={index}>
                    <span>
                      {value("status", row.status)} · {row.currency}
                    </span>
                    <div aria-hidden="true">
                      <i
                        style={{
                          width: `${(Number(row.source_rows) / Math.max(...data.items.map((item) => Number(item.source_rows)))) * 100}%`,
                        }}
                      />
                    </div>
                    <b>{row.source_rows} 单</b>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      ) : null}
    </>
  );
}
export default function ReportsView({ api }: { api: Api }) {
  const [name, setName] = useState<Kind>("inventory");
  return (
    <div className="reports-view">
      <div className="section-heading">
        <div>
          <p className="eyebrow">BUSINESS INSIGHTS</p>
          <h1>分析与报表</h1>
          <p className="muted">以真实业务记录为依据，在当前授权范围内分析。</p>
        </div>
        <BarChart3 size={30} aria-hidden="true" />
      </div>
      <div className="report-tabs" role="group" aria-label="报表类型">
        {(Object.keys(reports) as Kind[]).map((key) => (
          <button
            key={key}
            aria-pressed={name === key}
            className={name === key ? "primary" : ""}
            onClick={() => setName(key)}
          >
            {reports[key].title}
          </button>
        ))}
      </div>
      <Report key={name} api={api} name={name} />
    </div>
  );
}
