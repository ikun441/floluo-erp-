import { test, expect, type Page } from "@playwright/test";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../../..");
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "欢迎回来。" })).toBeVisible();
}
async function login(page: Page) {
  await page
    .getByRole("textbox", { name: "工作账号", exact: true })
    .fill("browser_admin");
  await page
    .getByRole("textbox", { name: "登录密码", exact: true })
    .fill("Browser-fixture-" + "x".repeat(20));
  await page.getByRole("button", { name: "进入工作空间", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "工作空间，一目了然。" }),
  ).toBeVisible();
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
