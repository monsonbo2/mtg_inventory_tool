import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

function visualArtifactPath(projectName: string, fileName: string) {
  const directory = path.join(process.cwd(), "test-results", "visual-review", projectName);
  mkdirSync(directory, { recursive: true });
  return path.join(directory, fileName);
}

async function openMainWorkspace(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Import Cards" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Quick Add and Card Search" })).toBeVisible();
}

async function openCollectionWithActivity(page: Page) {
  await openMainWorkspace(page);

  const activityButton = page.getByRole("button", { name: "Recent Activity" });
  if (await activityButton.isVisible().catch(() => false)) {
    return;
  }

  const switcherTrigger = page.locator(".inventory-focus-trigger").first();
  await expect(switcherTrigger).toBeVisible();
  await switcherTrigger.click();

  const switcherList = page.locator(".inventory-switcher-list");
  await expect(switcherList).toBeVisible();

  const preferredOptionNames = [/Personal Collection/i, /Helga Deck/i, /Trade Binder/i];
  let selectedOption = false;
  for (const optionName of preferredOptionNames) {
    const option = switcherList.getByRole("button", { name: optionName });
    if (await option.count()) {
      await option.first().click();
      selectedOption = true;
      break;
    }
  }

  if (!selectedOption) {
    await switcherList.getByRole("button").first().click();
  }

  await expect(activityButton).toBeVisible();
}

test.describe("visual review smoke", () => {
  test("captures the main workspace", async ({ page }, testInfo) => {
    await openMainWorkspace(page);

    await page.screenshot({
      path: visualArtifactPath(testInfo.project.name, "01-workspace.png"),
      fullPage: true,
    });
  });

  test("captures the import URL dialog", async ({ page }, testInfo) => {
    await openMainWorkspace(page);
    await page.getByRole("button", { name: "Import Cards" }).click();
    await page.getByRole("menuitem", { name: /Import from URL/i }).click();
    await expect(page.getByRole("dialog", { name: "Import From URL" })).toBeVisible();

    await page.screenshot({
      path: visualArtifactPath(testInfo.project.name, "02-import-url-dialog.png"),
      fullPage: true,
    });
  });

  test("captures the activity drawer", async ({ page }, testInfo) => {
    await openCollectionWithActivity(page);
    await page.getByRole("button", { name: "Recent Activity" }).click();
    await expect(page.getByRole("dialog", { name: "Collection Activity" })).toBeVisible();

    await page.screenshot({
      path: visualArtifactPath(testInfo.project.name, "03-activity-drawer.png"),
      fullPage: true,
    });
  });
});
