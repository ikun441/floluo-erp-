"use client";
import { useState, type FormEvent } from "react";
import LoginView from "./components/LoginView";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ArrowUpRight,
  Box,
  Building2,
  Check,
  ChevronRight,
  LayoutDashboard,
  LogOut,
  Moon,
  Plus,
  Search,
  ShieldCheck,
  Sun,
  Users,
  X,
} from "lucide-react";

type Data = Record<string, unknown>;
type Resource =
  | "products"
  | "users"
  | "departments"
  | "positions"
  | "roles"
  | "categories"
  | "suppliers"
  | "warehouses";
type ResourceSpec = { fields: string[]; actions: string[]; scopes: string[] };
type Rule = {
  id: string;
  subject: { kind: string; id?: string };
  resource: string;
  actions: string[];
  effect: string;
  scope: string;
  scope_ids?: string[];
  fields: Record<string, string>;
  conditions?: unknown[];
  requires_approval?: boolean;
};
const labels: Record<Resource, string> = {
  categories: "商品分类",
  suppliers: "供应商",
  warehouses: "仓库",
  products: "商品资料",
  users: "用户管理",
  departments: "部门管理",
  positions: "岗位管理",
  roles: "角色管理",
};
const fields: Record<Resource, string[]> = {
  products: [
    "sku",
    "name",
    "unit",
    "category_id",
    "owner_id",
    "department_id",
    "active",
  ],
  categories: ["name", "parent_id"],
  suppliers: [
    "code",
    "name",
    "contact",
    "phone",
    "owner_id",
    "department_id",
    "active",
  ],
  warehouses: ["code", "name", "owner_id", "department_id", "active"],
  users: [
    "username",
    "password",
    "department_id",
    "position_id",
    "supervisor_id",
    "role_ids",
    "active",
  ],
  departments: ["name", "parent_id"],
  positions: ["name"],
  roles: ["name"],
};
const names: Record<string, string> = {
  id: "标识",
  version: "版本",
  code: "编码",
  contact: "联系人",
  phone: "联系电话",
  category_id: "商品分类 ID",
  sku: "商品编码",
  name: "名称",
  unit: "单位",
  owner_id: "所属用户 ID",
  department_id: "部门 ID",
  active: "启用",
  username: "用户名",
  password: "密码（至少14字符）",
  position_id: "岗位 ID",
  supervisor_id: "主管 ID",
  role_ids: "角色 ID（逗号分隔）",
  parent_id: "上级 ID",
};
class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
async function api(path: string, init?: RequestInit) {
  const cookie = document.cookie
    .split("; ")
    .find((c) => c.startsWith("erp_csrf="));
  const csrf = cookie
    ? decodeURIComponent(cookie.slice("erp_csrf=".length))
    : "";
  const response = await fetch("/api/v1" + path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...init?.headers,
    },
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : "字段校验失败，请检查输入",
      response.status,
    );
  return data;
}
function ErrorBox({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  ) : null;
}
function useRecords(resource: Resource) {
  return useQuery<{ items: Data[] }>({
    queryKey: [resource],
    queryFn: () => api("/" + resource),
  });
}

function Editor({
  resource,
  row,
  close,
}: {
  resource: Resource;
  row?: Data;
  close: () => void;
}) {
  const qc = useQueryClient();
  const currentUser = qc.getQueryData<{ id: string }>(["me"]);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const form = new FormData(e.currentTarget);
    const data: Data = {};
    for (const key of fields[resource]) {
      const value = form.get(key);
      if (key === "password" && row && !value) continue;
      if (row && key !== "password" && !(key in row)) continue;
      data[key] =
        key === "active"
          ? value === "on"
          : key === "role_ids"
            ? String(value || "")
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            : key.endsWith("_id") || ["contact", "phone"].includes(key)
              ? value || null
              : value;
    }
    if (row) {
      for (const key of Object.keys(data)) {
        if (JSON.stringify(data[key]) === JSON.stringify(row[key]))
          delete data[key];
      }
    }
    try {
      await api("/" + resource + (row ? "/" + row.id : ""), {
        method: row ? "PATCH" : "POST",
        body: JSON.stringify({
          data,
          ...(row ? { version: row.version } : {}),
        }),
      });
      await qc.invalidateQueries({ queryKey: [resource] });
      close();
    } catch (err) {
      setError(err);
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
        aria-labelledby="editor-title"
      >
        <header>
          <h2 id="editor-title">
            {row ? "编辑" : "新建"}
            {labels[resource]}
          </h2>
          <button aria-label="关闭" onClick={close}>
            <X size={18} />
          </button>
        </header>
        <form onSubmit={submit}>
          {fields[resource].map((key) => (
            <label key={key}>
              {names[key]}
              {key === "active" ? (
                <input
                  type="checkbox"
                  name={key}
                  defaultChecked={row ? Boolean(row[key]) : true}
                />
              ) : (
                <input
                  name={key}
                  type={key === "password" ? "password" : "text"}
                  defaultValue={
                    Array.isArray(row?.[key])
                      ? (row[key] as string[]).join(",")
                      : String(
                          row?.[key] ??
                            (key === "owner_id" && !row
                              ? currentUser?.id
                              : "") ??
                            "",
                        )
                  }
                  required={
                    !key.endsWith("_id") &&
                    key !== "role_ids" &&
                    !(key === "password" && row) &&
                    !["contact", "phone"].includes(key)
                  }
                  minLength={key === "password" ? 14 : undefined}
                />
              )}
            </label>
          ))}
          <ErrorBox error={error} />
          <button className="primary" disabled={busy}>
            {busy ? "保存中…" : "保存资料"}
            <Check size={16} />
          </button>
        </form>
      </section>
    </div>
  );
}
function Records({ resource, search }: { resource: Resource; search: string }) {
  const query = useRecords(resource);
  const [edit, setEdit] = useState<{ row?: Data }>();
  const [after, setAfter] = useState<string>();
  const [previous, setPrevious] = useState<(string | undefined)[]>([]);
  const paged = useQuery<{ items: Data[] }>({
    queryKey: [resource, after],
    queryFn: () =>
      api(
        "/" +
          resource +
          "?limit=50" +
          (after ? "&after=" + encodeURIComponent(after) : ""),
      ),
    enabled: !!after,
  });
  const active = after ? paged : query;
  const rows =
    active.data?.items.filter((r) =>
      JSON.stringify(r).toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  const columns = Array.from(
    new Set(rows.flatMap((r) => Object.keys(r))),
  ).filter((k) => k !== "password");
  function next() {
    const last = active.data?.items.at(-1);
    if (last?.id) {
      setPrevious([...previous, after]);
      setAfter(String(last.id));
    }
  }
  function back() {
    setAfter(previous.at(-1));
    setPrevious(previous.slice(0, -1));
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">WORKSPACE / DIRECTORY</span>
          <h1>{labels[resource]}</h1>
          <p className="muted">维护当前账号有权访问的企业资料。</p>
        </div>
        <button className="primary" onClick={() => setEdit({})}>
          <Plus size={17} />
          新建资料
        </button>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h3>
            资料列表 <span className="badge">{rows.length}</span>
          </h3>
          <span className="muted">服务端授权过滤 · 每页50条</span>
        </div>
        <ErrorBox error={active.error} />
        {active.isPending ? (
          <p className="empty">正在加载资料…</p>
        ) : rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {columns.map((k) => (
                    <th key={k}>{names[k] || k}</th>
                  ))}
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={String(row.id ?? i)}>
                    {columns.map((k) => (
                      <td key={k} title={String(row[k] ?? "")}>
                        {typeof row[k] === "boolean" ? (
                          <span className="status">
                            {row[k] ? "启用" : "停用"}
                          </span>
                        ) : Array.isArray(row[k]) ? (
                          (row[k] as string[]).join(", ")
                        ) : (
                          String(row[k] ?? "—")
                        )}
                      </td>
                    ))}
                    <td>
                      {row.id && row.version ? (
                        <button
                          className="text-button"
                          onClick={() => setEdit({ row })}
                        >
                          编辑
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
        ) : (
          <div className="empty">
            <Box size={32} />
            <h3>暂无可见资料</h3>
            <p>新建第一条资料，或联系管理员确认访问范围。</p>
          </div>
        )}
        <div className="panel-footer">
          <span>仅展示有权读取的字段；搜索范围为当前页。</span>
          <div>
            <button disabled={!previous.length} onClick={back}>
              上一页
            </button>
            <button
              disabled={
                (active.data?.items.length ?? 0) < 50 ||
                !active.data?.items.at(-1)?.id
              }
              onClick={next}
            >
              下一页
            </button>
          </div>
        </div>
      </section>
      {edit ? (
        <Editor
          resource={resource}
          row={edit.row}
          close={() => {
            setEdit(undefined);
            void active.refetch();
          }}
        />
      ) : null}
    </>
  );
}
function newRule(): Rule {
  return {
    id: crypto.randomUUID(),
    subject: { kind: "role", id: "" },
    resource: "products",
    actions: ["read"],
    effect: "allow",
    scope: "own",
    scope_ids: [],
    fields: { id: "read", version: "read", sku: "read", name: "read" },
    conditions: [],
    requires_approval: false,
  };
}
function Permissions() {
  const qc = useQueryClient();
  const query = useQuery<{ number: number; rules: Rule[] }>({
    queryKey: ["policies"],
    queryFn: () => api("/policies"),
  });
  const catalog = useQuery<Record<string, ResourceSpec>>({
    queryKey: ["resource_catalog"],
    queryFn: () => api("/resource_catalog"),
  });
  const roles = useRecords("roles");
  const [draft, setDraft] = useState<Rule[]>();
  const [error, setError] = useState<unknown>();
  const [result, setResult] = useState<Data>();
  const [busy, setBusy] = useState(false);
  const rules = draft ?? query.data?.rules ?? [];
  function update(i: number, change: Partial<Rule>) {
    setDraft(rules.map((r, j) => (i === j ? { ...r, ...change } : r)));
  }
  async function publish() {
    setBusy(true);
    setError(undefined);
    try {
      const res = await api("/policies/publish", {
        method: "POST",
        body: JSON.stringify({
          expected_revision: query.data?.number ?? 0,
          rules,
        }),
      });
      setResult(res);
      setDraft(undefined);
      await qc.invalidateQueries();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  async function simulate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(undefined);
    try {
      setResult(
        await api("/policies/simulate", {
          method: "POST",
          body: JSON.stringify(
            Object.fromEntries(new FormData(e.currentTarget)),
          ),
        }),
      );
    } catch (err) {
      setError(err);
    }
  }
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">GOVERNANCE / ACCESS CONTROL</span>
          <h1>每一份权限，都有边界。</h1>
          <p className="muted">统一配置主体、数据范围和字段约束。</p>
        </div>
        <span className="version-pill">
          策略版本 {query.data?.number ?? "—"}
        </span>
      </div>
      <div className="notice">
        <ShieldCheck size={20} />
        <div>
          <strong>默认拒绝 · 明确拒绝优先</strong>
          <p>
            发布生成不可变版本。请保留管理员策略，避免所有管理员失去访问权限。
          </p>
        </div>
      </div>
      <ErrorBox error={query.error || catalog.error || error} />
      <section className="panel">
        <div className="panel-heading">
          <h3>访问策略矩阵</h3>
          <button onClick={() => setDraft([...rules, newRule()])}>
            <Plus size={16} />
            添加策略
          </button>
        </div>
        {rules.map((rule, i) => (
          <div className="rule" key={i}>
            <div className="rule-title">
              <span className="rule-number">
                {String(i + 1).padStart(2, "0")}
              </span>
              <input
                aria-label="策略标识"
                value={rule.id}
                onChange={(e) => update(i, { id: e.target.value })}
              />
              <button
                aria-label="移除策略"
                onClick={() => setDraft(rules.filter((_, j) => j !== i))}
              >
                <X size={16} />
              </button>
            </div>
            <div className="form-grid">
              <label>
                主体类型
                <select
                  value={rule.subject.kind}
                  onChange={(e) =>
                    update(i, {
                      subject:
                        e.target.value === "all"
                          ? { kind: "all" }
                          : { kind: e.target.value, id: "" },
                    })
                  }
                >
                  {["role", "user", "department", "all"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                主体 ID
                {rule.subject.kind === "role" ? (
                  <select
                    value={rule.subject.id || ""}
                    onChange={(e) =>
                      update(i, {
                        subject: { ...rule.subject, id: e.target.value },
                      })
                    }
                  >
                    <option value="">选择角色</option>
                    {roles.data?.items.map((r) => (
                      <option key={String(r.id)} value={String(r.id)}>
                        {String(r.name)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    disabled={rule.subject.kind === "all"}
                    value={rule.subject.id || ""}
                    onChange={(e) =>
                      update(i, {
                        subject: { ...rule.subject, id: e.target.value },
                      })
                    }
                  />
                )}
              </label>
              <label>
                资源
                <select
                  value={rule.resource}
                  onChange={(e) =>
                    update(i, {
                      resource: e.target.value,
                      actions: ["read"],
                      fields: {},
                      scope: "all",
                    })
                  }
                >
                  {Object.keys(catalog.data ?? {}).map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                效果
                <select
                  value={rule.effect}
                  onChange={(e) => update(i, { effect: e.target.value })}
                >
                  <option value="allow">允许</option>
                  <option value="deny">拒绝</option>
                </select>
              </label>
              <label>
                数据范围
                <select
                  value={rule.scope}
                  onChange={(e) => update(i, { scope: e.target.value })}
                >
                  {(catalog.data?.[rule.resource]?.scopes ?? []).map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                指定部门 / 记录 ID
                <input
                  value={rule.scope_ids?.join(",") || ""}
                  onChange={(e) =>
                    update(i, {
                      scope_ids: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </label>
            </div>
            <div className="actions-row">
              {(catalog.data?.[rule.resource]?.actions ?? []).map((action) => (
                <label key={action}>
                  <input
                    type="checkbox"
                    checked={rule.actions.includes(action)}
                    onChange={(e) =>
                      update(i, {
                        actions: e.target.checked
                          ? [...rule.actions, action]
                          : rule.actions.filter((a) => a !== action),
                      })
                    }
                  />
                  {action}
                </label>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={rule.requires_approval || false}
                  onChange={(e) =>
                    update(i, { requires_approval: e.target.checked })
                  }
                />
                需要审批
              </label>
            </div>
            <div className="field-matrix">
              {(catalog.data?.[rule.resource]?.fields ?? []).map((field) => (
                <label key={field}>
                  <span>{names[field] || field}</span>
                  <select
                    value={rule.fields[field] || "hidden"}
                    onChange={(e) =>
                      update(i, {
                        fields: { ...rule.fields, [field]: e.target.value },
                      })
                    }
                  >
                    {["hidden", "masked", "read", "write"]
                      .filter(
                        (v) =>
                          field !== "password" ||
                          ["hidden", "write"].includes(v),
                      )
                      .map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                  </select>
                </label>
              ))}
            </div>
            <details>
              <summary>条件规则 AST</summary>
              <textarea
                aria-label="条件规则"
                defaultValue={JSON.stringify(rule.conditions || [], null, 2)}
                onBlur={(e) => {
                  try {
                    const parsed: unknown = JSON.parse(e.target.value);
                    if (!Array.isArray(parsed)) throw new Error();
                    update(i, { conditions: parsed });
                    setError(undefined);
                  } catch {
                    setError(new Error("条件必须是 JSON 数组"));
                  }
                }}
              />
            </details>
          </div>
        ))}
        <div className="panel-footer">
          <span>审批工作流待实现，需审批的写操作当前会被拒绝。</span>
          <button
            className="primary"
            disabled={busy || !query.data}
            onClick={publish}
          >
            {busy ? "发布中…" : "发布新版本"}
            <ArrowUpRight size={16} />
          </button>
        </div>
      </section>
      <section className="panel padded">
        <span className="eyebrow">POLICY SIMULATOR</span>
        <h2>先验证，再授权。</h2>
        <p className="muted">输入真实用户和记录，查看统一引擎判定。</p>
        <form className="simulator" onSubmit={simulate}>
          <div className="form-grid">
            <label>
              用户 ID
              <input name="user_id" required />
            </label>
            <label>
              资源
              <select name="resource">
                {Object.keys(fields).map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              动作
              <select name="action">
                <option>read</option>
                <option>create</option>
                <option>update</option>
              </select>
            </label>
            <label>
              记录 ID
              <input name="record_id" required />
            </label>
          </div>
          <button>
            运行模拟
            <ChevronRight size={16} />
          </button>
        </form>
      </section>
      {result ? (
        <section className="panel padded">
          <h3>服务端结果</h3>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </section>
      ) : null}
    </>
  );
}
function Dashboard() {
  const products = useRecords("products"),
    users = useRecords("users"),
    departments = useRecords("departments");
  return (
    <>
      <div className="section-heading">
        <div>
          <span className="eyebrow">YOUR ENTERPRISE, CONNECTED</span>
          <h1>工作空间，一目了然。</h1>
          <p className="muted">从真实资料开始，让每次业务操作有迹可循。</p>
        </div>
        <span className="version-pill">
          <span className="dot" />
          基础设施开发中
        </span>
      </div>
      <div className="cards">
        {[
          ["可见商品资料", products],
          ["可见用户", users],
          ["可见部门", departments],
        ].map(([label, q]) => {
          const query = q as typeof products;
          return (
            <section className="metric" key={String(label)}>
              <span>{String(label)}</span>
              <strong>
                {query.isPending
                  ? "…"
                  : query.error
                    ? "—"
                    : (query.data?.items.length ?? 0)}
              </strong>
              <p>当前账号授权范围 · 首50条内</p>
            </section>
          );
        })}
      </div>
      <section className="welcome">
        <div>
          <span className="eyebrow">A SOLID FOUNDATION</span>
          <h2>
            把权限放在
            <br />
            每一步业务之前。
          </h2>
          <p>
            用户、角色和数据范围，共用一个授权边界。
            <br />
            Web 与后续消息入口保持一致。
          </p>
        </div>
        <div className="welcome-symbol">
          <ShieldCheck size={100} strokeWidth={1} />
        </div>
      </section>
      <div className="two-columns">
        <section className="panel padded">
          <h3>当前可用</h3>
          {[
            "真实用户认证与会话撤销",
            "组织、角色与商品基础资料",
            "版本化策略与权限模拟",
          ].map((s) => (
            <p className="checkline" key={s}>
              <Check size={17} />
              {s}
            </p>
          ))}
        </section>
        <section className="panel padded">
          <h3>接下来</h3>
          <p className="muted">
            采购与库存流水 → OneBot → 可选 AI → 审批 → 销售与报表。
          </p>
          <div className="notice compact">
            此版本为开发基础，尚无采购和库存业务，不展示虚构订单或统计。
          </div>
        </section>
      </div>
    </>
  );
}
function Workspace() {
  const qc = useQueryClient();
  const me = useQuery<{ username: string }>({
    queryKey: ["me"],
    queryFn: () => api("/auth/me"),
    retry: false,
  });
  const [page, setPage] = useState("dashboard"),
    [search, setSearch] = useState(""),
    [dark, setDark] = useState(false),
    [error, setError] = useState<unknown>();
  function resetSession() {
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    void qc.invalidateQueries({ queryKey: ["me"] });
  }
  if (me.isPending) return <main className="loading">正在连接工作空间…</main>;
  if (me.error instanceof ApiError && me.error.status === 401)
    return (
      <LoginView
        done={resetSession}
        authenticate={(username, password) =>
          api("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username, password }),
          })
        }
      />
    );
  if (me.error)
    return (
      <main className="loading">
        <h2>无法连接工作空间</h2>
        <ErrorBox error={me.error} />
        <button onClick={() => void me.refetch()}>重试连接</button>
      </main>
    );
  const nav = [
    { key: "dashboard", label: "工作概览", icon: LayoutDashboard },
    { key: "categories", label: "商品分类", icon: Box },
    { key: "suppliers", label: "供应商", icon: Building2 },
    { key: "warehouses", label: "仓库", icon: Building2 },
    { key: "products", label: "商品资料", icon: Box },
    { key: "users", label: "用户管理", icon: Users },
    { key: "departments", label: "部门管理", icon: Building2 },
    { key: "positions", label: "岗位管理", icon: Users },
    { key: "roles", label: "角色管理", icon: ShieldCheck },
    { key: "policies", label: "权限中心", icon: ShieldCheck },
  ];
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      resetSession();
    } catch (err) {
      setError(err);
    }
  }
  return (
    <div className={"app" + (dark ? " dark" : "")}>
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">弗</span>
          <span>
            弗洛洛 <b>ERP</b>
            <small>ENTERPRISE WORKSPACE</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="dot" />
          企业工作空间<small>LOCAL WORKSPACE</small>
        </div>
        <span className="nav-label">工作台</span>
        <nav>
          {nav.map((n) => (
            <button
              key={n.key}
              className={page === n.key ? "selected" : ""}
              onClick={() => {
                setPage(n.key);
                setSearch("");
              }}
            >
              <n.icon size={18} />
              {n.label}
              {page === n.key ? <ChevronRight size={15} /> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={18} />
          <span>
            统一授权，安心协作<small>v1.0.0 · 开发版</small>
          </span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>
            工作空间 <ChevronRight size={14} />
            <b>{nav.find((n) => n.key === page)?.label}</b>
          </span>
          <div className="top-actions">
            <label className="search">
              <Search size={16} />
              <input
                aria-label="搜索当前页可见资料"
                placeholder="搜索当前页资料…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <button aria-label="切换主题" onClick={() => setDark(!dark)}>
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <span className="avatar">
              {me.data?.username.slice(0, 1).toUpperCase()}
            </span>
            <span className="username">{me.data?.username}</span>
            <button aria-label="退出登录" onClick={logout}>
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main className="content">
          <ErrorBox error={error} />
          {page === "dashboard" ? (
            <Dashboard />
          ) : page === "policies" ? (
            <Permissions />
          ) : (
            <Records key={page} resource={page as Resource} search={search} />
          )}
          <footer>
            弗洛洛 ERP<span>企业工作，从这里有序开始。</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
export default function Page() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 0, refetchOnWindowFocus: true },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Workspace />
    </QueryClientProvider>
  );
}
