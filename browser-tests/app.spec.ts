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

/**
 * A registry with something in it: does the first screen still scale?
 *
 * The critique photographed thirty-odd rows here — an unbounded, unsearchable list where
 * every row wore the same badge — so the case is measured with a registry, not with the
 * one project the other tests make. Six projects are registered through the daemon with
 * their last openings spread over the three ages, because the ages are the one thing a
 * unit test can fake and a browser cannot.
 */
test('a registry of many projects groups by age and answers a find', async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const seeded = await request.post('/__test__/aged-projects');
  expect(seeded.ok()).toBeTruthy();
  const { tag, projects } = (await seeded.json()) as {
    tag: string;
    projects: { project_id: string; name: string; age: string }[];
  };

  const response = await request.get('/__test__/bootstrap');
  const { nonce } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);

  // The product names itself before it lists anything, and the registry is a section of
  // that screen rather than the screen itself.
  await expect(page.getByRole('heading', { level: 1, name: 'Research Harness' })).toBeVisible();
  await expect(
    page.getByRole('heading', { level: 2, name: 'Your research projects' }),
  ).toBeVisible();

  const list = page.getByRole('list', { name: 'Registered projects' });
  await expect(list).toBeVisible();

  // Each seeded project under the naming line for its own age. The count on the line is
  // the whole run's, and other tests register projects into the same registry, so the age
  // is asserted by membership rather than by a number.
  for (const project of projects) {
    const run = list.getByRole('list', { name: new RegExp(`^${project.age} — \\d+ projects?$`) });
    await expect(run.getByRole('heading', { name: project.name, exact: true })).toBeVisible();
  }

  // The badge is the exception now: an ordinary row says nothing about its availability.
  await expect(page.getByText('Available', { exact: true })).toHaveCount(0);

  const find = page.getByRole('searchbox', { name: 'Find a project by name or folder' });
  await find.fill(tag);
  await expect(list.getByRole('heading')).toHaveCount(projects.length);
  await find.fill('nothing here answers to this');
  await expect(page.getByText('No project matches this find')).toBeVisible();
  await page.getByRole('button', { name: 'Clear the find' }).click();
  await expect(list.getByRole('heading', { name: projects[0]!.name, exact: true })).toBeVisible();

  // The two widths the cockpit claims to support, with a registry on screen at both.
  const original = page.viewportSize();
  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(list).toBeVisible();
    expect(await axeViolations(page), `Project home with a registry at ${width}`).toEqual([]);
    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(fits, `Project home must not overflow horizontally at ${width}`).toBeTruthy();
    await page.screenshot({ path: info.outputPath(`project-registry-${width}.png`), fullPage: true });
  }
  if (original) await page.setViewportSize(original);
  expect(errors).toEqual([]);
});

test('an unauthenticated browser cannot create projects', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Not signed in to the local application');
  await expect(page.getByRole('button', { name: 'New project', exact: true })).toBeDisabled();
  const response = await request.post('/api/projects/create', { data: { parent: '.', name: 'forbidden' } });
  expect(response.status()).toBe(401);
});
