import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

test('project creation and rename persist through the real API and reload', async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await expect(page).not.toHaveURL(/bootstrap=/);
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  const name = `Browser study ${info.project.name}`;
  await page.getByLabel('Project name', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse((r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  if (info.project.name === 'narrow-light') {
    await expect(page.locator('.rh-app-shell__drawer[hidden]').first()).toBeHidden();
    await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  }
  await expect(page.getByRole('button', { name: new RegExp(`Project: ${name}\\.`) })).toBeVisible();
  const projectURL = page.url();
  await page.reload();
  if (info.project.name === 'narrow-light') {
    await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  }
  await expect(page.getByRole('button', { name: new RegExp(`Project: ${name}\\.`) })).toBeVisible();
  await expect(page).toHaveURL(projectURL);
  await page.getByRole('button', { name: 'Project actions', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Rename', exact: true }).click();
  await page.getByLabel('Display name').fill(`${name} revised`);
  await page.getByRole('button', { name: 'Rename project', exact: true }).click();
  await expect(page.getByRole('button', { name: new RegExp(`Project: ${name} revised\\.`) })).toBeVisible();
  await page.reload();
  if (info.project.name === 'narrow-light') {
    await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  }
  await expect(page.getByRole('button', { name: new RegExp(`Project: ${name} revised\\.`) })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New session', exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('workspace.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('project home teaches what a project is, at both widths', async ({ page, request }, info) => {
  const original = page.viewportSize();
  const response = await request.get('/__test__/bootstrap');
  const { nonce } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('button', { name: 'New project', exact: true })).toBeEnabled();
  await expect(page.locator('html')).toHaveAttribute('data-theme', info.project.name.endsWith('light') ? 'light' : 'dark');

  // This is the first screen of the product, and the only one that can define the object
  // every other screen belongs to. It has to do that on a laptop and on a tablet held
  // upright — the two widths the cockpit claims to support — without overflowing either.
  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.getByText(/A project is a folder on this machine/)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
    expect(await axeViolations(page), `Project home at ${width}`).toEqual([]);
    const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(fits, `Project home must not overflow horizontally at ${width}`).toBeTruthy();
    await page.screenshot({ path: info.outputPath(`project-home-${width}.png`), fullPage: true });
  }

  if (original) await page.setViewportSize(original);
  await page.screenshot({ path: info.outputPath('project-home.png'), fullPage: true });
});

test('an unauthenticated browser cannot create projects', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Not signed in to the local application');
  await expect(page.getByRole('button', { name: 'New project', exact: true })).toBeDisabled();
  const response = await request.post('/api/projects/create', { data: { parent: '.', name: 'forbidden' } });
  expect(response.status()).toBe(401);
});
