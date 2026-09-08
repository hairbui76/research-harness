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
  // Scoped to the rail: with no session open the composer offers the same control, by the
  // same name, in the same window (wave six's front door).
  await expect(
    page
      .getByRole('navigation', { name: 'Project navigation' })
      .getByRole('button', { name: 'New session', exact: true }),
  ).toBeEnabled();
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

  /*
   * The runs, read off the sequence the list is in.
   *
   * The registry is windowed, so a run cannot be a container: only a slice of the list is
   * mounted at a time. A naming line, then the workspaces it names, then the next line is
   * what carries the grouping — on screen, and in the order a reader is walked through.
   */
  const runs = (): Promise<{ line: string; projects: string[] }[]> =>
    list.evaluate((root) => {
      const found: { line: string; projects: string[] }[] = [];
      for (const item of Array.from(root.querySelectorAll('.rh-virtual-list__item'))) {
        const line = item.querySelector('.rh-projects__group-heading');
        if (line !== null) {
          found.push({ line: (line.textContent ?? '').trim(), projects: [] });
          continue;
        }
        const name = item.querySelector('.rh-projects__name');
        if (name !== null) found.at(-1)?.projects.push((name.textContent ?? '').trim());
      }
      return found;
    });

  const find = page.getByRole('searchbox', { name: 'Find a project by name or folder' });
  // The find first, because other tests register projects into the same registry and only
  // a window of it is mounted: what is asserted below is these six, all of them on screen.
  await find.fill(tag);
  await expect(list.getByRole('heading')).toHaveCount(projects.length);

  // Each seeded project under the naming line for its own age. The count on the line is
  // the whole run's, so the age is asserted by membership rather than by a number.
  const grouped = await runs();
  for (const project of projects) {
    const run = grouped.find((entry) => entry.line.startsWith(`${project.age} — `));
    expect(run, `no run named ${project.age} on screen`).toBeTruthy();
    expect(run?.projects, `${project.name} is not under ${project.age}`).toContain(project.name);
  }

  // The workspace's name is the way in: one act per row, and no filled button repeated
  // down a registry of forty-odd.
  const first = list.getByRole('link', { name: projects[0]!.name, exact: true });
  await expect(first).toHaveAttribute('href', new RegExp(`/projects/${projects[0]!.project_id}/$`));
  await expect(list.getByRole('button', { name: 'Open', exact: true })).toHaveCount(0);

  // The badge is the exception now: an ordinary row says nothing about its availability.
  await expect(page.getByText('Available', { exact: true })).toHaveCount(0);

  await find.fill('nothing here answers to this');
  await expect(page.getByText('No project matches this find')).toBeVisible();
  await page.getByRole('button', { name: 'Clear the find' }).click();
  await expect(list.getByRole('heading', { name: projects[0]!.name, exact: true })).toBeVisible();

  /*
   * And the whole registry is a window onto itself.
   *
   * The list states how long it is on every item it mounts, so a reader is told where they
   * stand in the registry rather than in the slice that happens to exist. Nothing here
   * assumes how many projects the run's other tests have left behind: what is asserted is
   * that no more rows are mounted than the list says it holds, and that a registry longer
   * than the window mounts fewer than it holds.
   */
  const bounds = await list.evaluate((root) => {
    const items = Array.from(root.querySelectorAll('.rh-virtual-list__item'));
    return {
      mounted: items.length,
      held: Number(items[0]?.getAttribute('aria-setsize') ?? 0),
    };
  });
  expect(bounds.mounted, 'the registry mounts more rows than it holds').toBeLessThanOrEqual(
    bounds.held,
  );
  if (bounds.held > 40) {
    expect(bounds.mounted, `a registry of ${bounds.held} mounted ${bounds.mounted}`).toBeLessThan(
      bounds.held,
    );
  }

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
