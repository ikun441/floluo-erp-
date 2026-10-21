import { test, expect, type Page } from "@playwright/test";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../../..");
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "欢迎回来。" })).toBeVisible();
  await expect(page.locator(".stage-brand img")).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".stage-brand img")
        .evaluate((img) => (img as HTMLImageElement).naturalWidth),
    )
    .toBe(1254);
}
async function login(
  page: Page,
  username = "browser_admin",
  password = "Browser-fixture-" + "x".repeat(20),
) {
  await page
    .getByRole("textbox", { name: "工作账号", exact: true })
    .fill(username);
  await page
    .getByRole("textbox", { name: "登录密码", exact: true })
    .fill(password);
  await page.getByRole("button", { name: "进入工作空间", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "工作空间，一目了然。" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".brand img")
        .evaluate((img) => (img as HTMLImageElement).naturalWidth),
    )
    .toBe(1254);
}

test("real login, persisted department, permission UI and logout", async ({
  page,
}) => {
  await open(page);
  await login(page);
  await page.getByRole("button", { name: "部门管理", exact: true }).click();
  await page.getByRole("button", { name: "新建资料", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const name = "browser-verification-" + Date.now();
  await dialog.getByRole("textbox", { name: "名称", exact: true }).fill(name);
  await dialog.getByRole("button", { name: "保存资料", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "工作空间，一目了然。" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "部门管理", exact: true }).click();
  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "权限中心", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "访问策略矩阵", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "发布新版本", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "欢迎回来。" })).toBeVisible();
  await expect(page.locator(".stage-brand img")).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".stage-brand img")
        .evaluate((img) => (img as HTMLImageElement).naturalWidth),
    )
    .toBe(1254);
});

test("real WebGL scene, pause control and password visibility", async ({
  page,
}) => {
  await open(page);
  await expect(page.locator(".sculpture-host")).toHaveAttribute(
    "data-webgl",
    "ready",
  );
  await expect(page.locator(".login-scene-wrap")).toHaveCSS("opacity", "1");
  await page.getByRole("button", { name: "显示密码", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "登录密码", exact: true }),
  ).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "隐藏密码", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "登录密码", exact: true }),
  ).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "暂停背景动画", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "播放背景动画", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    await page
      .locator(".feature-data")
      .evaluate((el) => getComputedStyle(el).animationPlayState),
  ).toBe("paused");
  await page.screenshot({
    path: path.join(root, "output/playwright/login-desktop.png"),
  });
});

test("mobile and reduced motion remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page);
  await expect(page.locator(".sculpture-host")).toHaveAttribute(
    "data-webgl",
    "ready",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    await page
      .locator(".login-scene-wrap")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  await page.screenshot({
    path: path.join(root, "output/playwright/login-mobile.png"),
    fullPage: true,
  });
  await login(page);
});

test("no WebGL still supports real authentication", async ({ page }) => {
  await page.addInitScript(() => {
    const proto = HTMLCanvasElement.prototype as unknown as {
      getContext: (
        this: HTMLCanvasElement,
        id: string,
        ...args: unknown[]
      ) => unknown;
    };
    const original = proto.getContext;
    proto.getContext = function (id, ...args) {
      if (id.includes("webgl")) return null;
      return original.call(this, id, ...args);
    };
  });
  await open(page);
  await expect(page.locator(".sculpture-failed")).toBeVisible();
  await login(page);
});

test("catalog records persist through real UI and registry drives policy fields", async ({
  page,
}) => {
  await open(page);
  await login(page);
  for (const resource of ["商品分类", "供应商", "仓库"]) {
    await page.getByRole("button", { name: resource, exact: true }).click();
    await page.getByRole("button", { name: "新建资料", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const name = resource + "-browser-" + Date.now();
    await dialog.getByRole("textbox", { name: "名称", exact: true }).fill(name);
    if (resource !== "商品分类") {
      await dialog
        .getByRole("textbox", { name: "编码", exact: true })
        .fill("browser-" + Date.now());
      await expect(
        dialog.getByRole("textbox", { name: "所属用户 ID", exact: true }),
      ).not.toHaveValue("");
    }
    if (resource === "供应商") {
      await dialog
        .getByRole("textbox", { name: "联系人", exact: true })
        .fill("Browser Fixture");
    }
    await dialog.getByRole("button", { name: "保存资料", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: resource, exact: true }).click();
    await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "权限中心", exact: true }).click();
  const supplierRule = page
    .locator(".rule")
    .filter({ has: page.locator('input[value="bootstrap-suppliers"]') });
  await expect(supplierRule.getByText("联系人", { exact: true })).toBeVisible();
  const categoryRule = page
    .locator(".rule")
    .filter({ has: page.locator('input[value="bootstrap-categories"]') });
  await expect(
    categoryRule.getByLabel("数据范围").locator('option[value="own"]'),
  ).toHaveCount(0);
});

test("two real users approve and receive a purchase into inventory", async ({
  page,
  browser,
}) => {
  await open(page);
  await login(page);
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === "erp_csrf",
  )!.value;
  const headers = { "x-csrf-token": csrf };
  const identity = await (await page.request.get("/api/v1/auth/me")).json();
  const admin = await (
    await page.request.get("/api/v1/users/" + identity.id)
  ).json();
  const suffix = String(Date.now());
  async function create(resource: string, data: Record<string, unknown>) {
    const response = await page.request.post("/api/v1/" + resource, {
      headers,
      data: { data },
    });
    expect(response.status()).toBe(200);
    return response.json();
  }
  const supplier = await create("suppliers", {
    code: "flow-s-" + suffix,
    name: "Flow Supplier " + suffix,
    owner_id: identity.id,
  });
  const warehouse = await create("warehouses", {
    code: "flow-w-" + suffix,
    name: "Flow Warehouse " + suffix,
    owner_id: identity.id,
  });
  const product = await create("products", {
    sku: "flow-p-" + suffix,
    name: "Flow Product " + suffix,
    unit: "piece",
    owner_id: identity.id,
  });
  const approverName = "approver_" + suffix;
  const approverPassword = "Browser-approver-" + "x".repeat(20);
  await create("users", {
    username: approverName,
    password: approverPassword,
    role_ids: admin.role_ids,
  });
  await page.getByRole("button", { name: "采购业务规则", exact: true }).click();
  await page
    .getByRole("textbox", { name: "支持币种（逗号分隔）", exact: true })
    .fill("CNY");
  await page.getByLabel("税模式", { exact: true }).selectOption("no_tax");
  const configuration = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/system_configuration") &&
      response.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "保存业务规则", exact: true }).click();
  expect((await configuration).status()).toBe(200);
  await page.getByRole("button", { name: "采购订单", exact: true }).click();
  await page.getByRole("button", { name: "新建采购单", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("供应商", { exact: true }).selectOption(supplier.id);
  await dialog.getByLabel("币种", { exact: true }).fill("CNY");
  await dialog.getByLabel("商品", { exact: true }).selectOption(product.id);
  await dialog.getByLabel("数量", { exact: true }).fill("3");
  await dialog.getByLabel("单价", { exact: true }).fill("20.00");
  const creating = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/purchase_orders") &&
      response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "保存草稿", exact: true }).click();
  const created = await (await creating).json();
  await expect(dialog).not.toBeVisible();
  await page
    .getByRole("row")
    .filter({ hasText: created.number })
    .getByRole("button", { name: "查看采购单", exact: true })
    .click();
  await page.getByRole("button", { name: "提交审批", exact: true }).click();
  await page.getByRole("button", { name: "批准采购单", exact: true }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "采购单创建人不能审批自己的订单" }),
  ).toContainText("采购单创建人不能审批自己的订单");
  const context = await browser.newContext({
    baseURL: "http://127.0.0.1:3000",
  });
  try {
    const approver = await context.newPage();
    await open(approver);
    await login(approver, approverName, approverPassword);
    await approver
      .getByRole("button", { name: "采购订单", exact: true })
      .click();
    await approver
      .getByRole("row")
      .filter({ hasText: created.number })
      .getByRole("button", { name: "查看采购单", exact: true })
      .click();
    await approver
      .getByRole("button", { name: "批准采购单", exact: true })
      .click();
    await expect(
      approver.getByRole("button", { name: "登记入库", exact: true }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
  await page.reload();
  await page.getByRole("button", { name: "采购订单", exact: true }).click();
  await page
    .getByRole("row")
    .filter({ hasText: created.number })
    .getByRole("button", { name: "查看采购单", exact: true })
    .click();
  await page.getByRole("button", { name: "登记入库", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("入库仓库", { exact: true })
    .selectOption(warehouse.id);
  await dialog.getByRole("textbox").fill("3");
  await dialog.getByRole("button", { name: "确认入库", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText(/状态：已入库/)).toBeVisible();
  await page.screenshot({
    path: path.join(root, "output/playwright/purchase-order.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "库存与入库", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "3.0000", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "库存流水", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "purchase_receipt", exact: true }),
  ).toBeVisible();
});

test("message control plane persists instances and clears one-time secrets", async ({
  page,
}) => {
  await open(page);
  await login(page);
  await page.getByRole("button", { name: "消息接入", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "消息机器人", exact: true }),
  ).toBeVisible();
  const name = "browser-bot-" + Date.now();
  await page.getByLabel("实例名称", { exact: true }).fill(name);
  await page.getByLabel("机器人 QQ（bot_id）", { exact: true }).fill("10001");
  const created = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/onebot_instances") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "创建实例", exact: true }).click();
  expect((await created).status()).toBe(200);
  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "访问令牌（仅显示一次）", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除令牌", exact: true }).click();
  await page.locator('input[name="platform_user_id"]').fill("20002");
  await page
    .locator('input[name="password"]')
    .fill("Browser-fixture-" + "x".repeat(20));
  const issued = page.waitForResponse((r) =>
    r.url().endsWith("/api/v1/message_binding_challenges"),
  );
  await page.getByRole("button", { name: "生成绑定命令", exact: true }).click();
  expect((await issued).status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "待发送的绑定命令", exact: true }),
  ).toBeVisible();
  await expect(page.locator('input[name="password"]')).toHaveValue("");
  await page.getByRole("button", { name: "清除命令", exact: true }).click();
  const row = page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name, exact: true }) });
  await row.getByRole("button", { name: "轮换令牌", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "访问令牌（仅显示一次）", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清除令牌", exact: true }).click();
  await row.getByRole("button", { name: "停用", exact: true }).click();
  await expect(
    row.getByRole("cell", { name: "已停用", exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "消息接入", exact: true }).click();
  await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "访问令牌（仅显示一次）", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "待发送的绑定命令", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: path.join(root, "output/playwright/messaging.png"),
    fullPage: true,
  });
});

test("operation workbench previews, confirms a real draft and cancels partial requests", async ({
  page,
}) => {
  await open(page);
  await login(page);
  const csrf = (await page.context().cookies()).find(
    (c) => c.name === "erp_csrf",
  )!.value;
  const identity = await (await page.request.get("/api/v1/auth/me")).json();
  const suffix = String(Date.now());
  async function catalog(resource: string, data: Record<string, unknown>) {
    const r = await page.request.post("/api/v1/" + resource, {
      headers: { "x-csrf-token": csrf },
      data: { data: { ...data, owner_id: identity.id } },
    });
    expect(r.status()).toBe(200);
    return r.json();
  }
  const product = await catalog("products", {
    sku: "operation-p-" + suffix,
    name: "Operation Product " + suffix,
    unit: "piece",
  });
  const supplier = await catalog("suppliers", {
    code: "operation-s-" + suffix,
    name: "Operation Supplier " + suffix,
  });
  await page.getByRole("button", { name: "操作工作台", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "操作工作台", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "发起采购请求", exact: true }).click();
  const editor = page.getByRole("region", {
    name: "新建采购请求",
    exact: true,
  });
  await editor.getByLabel("商品", { exact: true }).selectOption(product.id);
  await editor.getByLabel("供应商", { exact: true }).selectOption(supplier.id);
  await editor.getByLabel("数量", { exact: true }).fill("2");
  await editor.getByLabel("单价", { exact: true }).fill("12.50");
  await editor.getByLabel("币种", { exact: true }).fill("CNY");
  const creating = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/message_operations") &&
      r.request().method() === "POST",
  );
  await editor.getByRole("button", { name: "保存请求", exact: true }).click();
  const operation = await (await creating).json();
  expect(operation.state).toBe("awaiting_confirmation");
  await expect(
    page.getByRole("heading", { name: "采购草稿预览", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("25.00 CNY", { exact: true })).toBeVisible();
  await page.screenshot({
    path: path.join(root, "output/playwright/operations-desktop.png"),
    fullPage: true,
  });
  const before = await page.request.get(
    "/api/v1/purchase_orders/" + operation.preview.number.slice(3),
  );
  expect(before.status()).toBe(404);
  const confirm = page.getByRole("form", { name: "确认请求", exact: true });
  await confirm.getByLabel("当前 ERP 密码", { exact: true }).fill("incorrect");
  const wrong = page.waitForResponse(
    (r) => r.url().endsWith("/confirm") && r.request().method() === "POST",
  );
  await confirm
    .getByRole("button", { name: "确认创建采购草稿", exact: true })
    .click();
  expect((await wrong).status()).toBe(403);
  await expect(
    confirm.getByLabel("当前 ERP 密码", { exact: true }),
  ).toHaveValue("");
  await confirm
    .getByLabel("当前 ERP 密码", { exact: true })
    .fill("Browser-fixture-" + "x".repeat(20));
  const confirmed = page.waitForResponse(
    (r) => r.url().endsWith("/confirm") && r.request().method() === "POST",
  );
  await confirm
    .getByRole("button", { name: "确认创建采购草稿", exact: true })
    .click();
  const done = await (await confirmed).json();
  expect(done.state).toBe("completed");
  await expect(
    page.getByRole("heading", { name: "采购草稿已创建", exact: true }),
  ).toBeVisible();
  const order = await page.request.get(
    "/api/v1/purchase_orders/" + done.result_id,
  );
  expect((await order.json()).total).toBe("25.00");
  await page.getByRole("button", { name: "发起采购请求", exact: true }).click();
  const partial = page.getByRole("region", {
    name: "新建采购请求",
    exact: true,
  });
  await partial.getByLabel("商品", { exact: true }).selectOption(product.id);
  await partial.getByRole("button", { name: "保存请求", exact: true }).click();
  await expect(page.getByText("还需补充：", { exact: false })).toBeVisible();
  await page
    .getByRole("region", { name: "我的请求", exact: true })
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "待补充", exact: true }) })
    .getByRole("button", { name: "取消请求", exact: true })
    .click();
  await expect(
    page.getByText("该请求不会创建订单，如需操作请重新发起。", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("请求状态", { exact: true }).selectOption("cancelled");
  await expect(
    page.getByRole("cell", { name: "已取消", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(root, "output/playwright/operations-mobile.png"),
    fullPage: true,
  });
});

test("offline assistant parses without writes and saves a unit-checked pending request", async ({
  page,
}) => {
  await open(page);
  await login(page);
  const csrf = (await page.context().cookies()).find(
    (c) => c.name === "erp_csrf",
  )!.value;
  const identity = await (await page.request.get("/api/v1/auth/me")).json();
  const suffix = Date.now().toString();
  async function catalog(resource: string, data: Record<string, unknown>) {
    const response = await page.request.post("/api/v1/" + resource, {
      headers: { "x-csrf-token": csrf },
      data: { data: { ...data, owner_id: identity.id } },
    });
    expect(response.ok()).toBe(true);
    return response.json();
  }
  const product = await catalog("products", {
    sku: "local-p-" + suffix,
    name: "Local Mouse " + suffix,
    unit: "个",
  });
  const supplier = await catalog("suppliers", {
    code: "local-s-" + suffix,
    name: "Local Supplier " + suffix,
  });
  await page.getByRole("button", { name: "操作工作台", exact: true }).click();
  const assistant = page.getByRole("region", {
    name: "离线指令助手",
    exact: true,
  });
  const text = assistant.getByLabel("业务描述", { exact: true });
  await text.fill(
    `登记采购2个"${product.name}"，每个12.50元，供应商=${supplier.id}，币种=CNY。`,
  );
  await assistant
    .getByRole("button", { name: "识别描述", exact: true })
    .click();
  await expect(
    assistant.getByRole("heading", {
      name: "识别结果：发起采购请求",
      exact: true,
    }),
  ).toBeVisible();
  const before = await page.request.get("/api/v1/message_operations");
  const beforeIds = (await before.json()).items.map(
    (r: { id: string }) => r.id,
  );
  const saving = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/intents/requests") &&
      r.request().method() === "POST",
  );
  await assistant
    .getByRole("button", { name: "生成待确认请求", exact: true })
    .click();
  const row = await (await saving).json();
  expect(beforeIds).not.toContain(row.id);
  expect(row.state).toBe("awaiting_confirmation");
  expect(row.preview.product.unit).toBe("个");
  await expect(
    page.getByRole("heading", { name: "采购草稿预览", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("25.00 CNY", { exact: true })).toBeVisible();
  const absent = await page.request.get(
    "/api/v1/purchase_orders/" + row.preview.number.slice(3),
  );
  expect(absent.status()).toBe(404);
  await text.fill(`查询"${product.name}"库存`);
  await assistant
    .getByRole("button", { name: "识别描述", exact: true })
    .click();
  await expect(
    assistant.getByRole("heading", { name: "识别结果：查询库存", exact: true }),
  ).toBeVisible();
  await assistant
    .getByRole("button", { name: "执行授权查询", exact: true })
    .click();
  await expect(
    assistant.getByText("当前授权范围内没有匹配记录。", { exact: true }),
  ).toBeVisible();
  await text.fill("审批所有采购单");
  await assistant
    .getByRole("button", { name: "识别描述", exact: true })
    .click();
  await expect(assistant.getByRole("alert")).toContainText("未能识别");
  await expect(
    assistant.getByRole("button", { name: "执行授权查询", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: path.join(root, "output/playwright/offline-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(root, "output/playwright/offline-mobile.png"),
    fullPage: true,
  });
});
