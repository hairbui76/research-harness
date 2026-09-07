/**
 * Type and target floors, measured in a real browser.
 *
 * Everything here is a property the token files claim and only a layout engine can
 * confirm. jsdom resolves no `var()` and computes no geometry, so the design package's
 * token tests read the stylesheet and the component tests read class names; what neither
 * can see is the number that actually lands on the glyph after the cascade, the density
 * attribute, the density's font scale and `max()` have all had their say.
 *
 * Four claims are checked on the Overview, the Corpus and the manuscript workspace:
 *
 * 1. An `<h1>` is one size. It used to be 28px on a research page, 15px in the
 *    conversation and 13px on the manuscript toolbar — three sizes for the one element
 *    that names a screen for the eye and for the screen reader arriving from the skip
 *    link.
 * 2. No heading renders smaller than the body text under it. `h4` was 13px against a 14px
 *    body, which inverts what a heading is for; it is body size now and carries its weight
 *    instead.
 * 3. Every button and non-inline link is at least a 24x24 pointer target (WCAG 2.2
 *    SC 2.5.8). Compact density used to take an icon button to 22x22.
 * 4. A research table's cell is at least 12px. The cells used to compute to 11.15px,
 *    because the compact wrapper's font scale was applied to a 12px role.
 *
 * The Corpus is the surface the table check runs on: a brand-new project has no rows, so
 * the shipped `.rh-web-table` rule is measured on an element mounted into the real page,
 * inside the same compact wrapper `DataTable` puts around it, and taken away again.
 */
import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** The reading floor and the pointer-target floor, as the token files declare them. */
const READING_FLOOR = 12;
const TARGET_FLOOR = 24;

interface HeadingSizes {
  body: number;
  h1: number;
  /** Every visible `h2`-`h4`, as `tag@size`, so a failure names the heading that broke. */
  subheadings: string[];
}

/** What the browser computed for the headings on the page as it stands. */
async function headingSizes(page: import('@playwright/test').Page): Promise<HeadingSizes> {
  return page.evaluate(() => {
    const visible = (element: Element): boolean => {
      const rect = element.getBoundingClientRect();
      return rect.width > 1 && rect.height > 1;
    };
    const size = (element: Element): number =>
      Number.parseFloat(getComputedStyle(element).fontSize);
    const h1 = [...document.querySelectorAll('h1')].filter(visible)[0];
    return {
      body: size(document.body),
      h1: h1 ? size(h1) : 0,
      subheadings: [...document.querySelectorAll('h2, h3, h4')]
        .filter(visible)
        .map((element) => `${element.tagName.toLowerCase()}@${size(element)}`),
    };
  });
}

/**
 * Every button and link whose box is under the pointer-target floor.
 *
 * Two exclusions, both of them WCAG's own. A control that is not rendered at all — the
 * skip link parked at 1x1 until it takes focus — has no target to measure, and a link
 * set `display: inline` is a word inside a sentence, which SC 2.5.8 exempts because the
 * line it sits on decides its height.
 */
async function undersizedTargets(page: import('@playwright/test').Page, floor: number) {
  return page.evaluate((minimum) => {
    const out: string[] = [];
    for (const element of document.querySelectorAll('button, a[href], [role="button"]')) {
      const rect = element.getBoundingClientRect();
      if (rect.width <= 1 || rect.height <= 1) continue;
      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') continue;
      if (element.tagName === 'A' && style.display === 'inline') continue;
      if (rect.width < minimum || rect.height < minimum) {
        const label = (element.textContent ?? '').trim().slice(0, 40) || element.className;
        out.push(`${element.tagName.toLowerCase()} "${label}" ${rect.width}x${rect.height}`);
      }
    }
    return out;
  }, floor);
}

test('the cockpit sets one h1, no heading under body, and no target under 24px', async ({
  page,
  request,
}, info) => {
  // Three surfaces, each with a mounted-and-removed probe and a screenshot.
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`Typeset ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  const h1Sizes = new Map<string, number>();

  for (const surface of ['overview', 'corpus', 'manuscript']) {
    await page.goto(`${workspace}/${surface}`);
    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading, `${surface} must name itself with an h1`).toBeVisible();
    // The frame arrives before its body does, and a half-rendered page would be measured
    // for whatever happened to be mounted — which is how a 21px action link stayed hidden
    // from this check on a fast machine and appeared on a slow one.
    await page.waitForLoadState('networkidle');

    const sizes = await headingSizes(page);
    h1Sizes.set(surface, sizes.h1);

    // A heading never renders smaller than the paragraph it introduces.
    for (const subheading of sizes.subheadings) {
      const measured = Number(subheading.split('@')[1]);
      expect(
        measured,
        `${surface}: ${subheading} is under the ${sizes.body}px body`,
      ).toBeGreaterThanOrEqual(sizes.body);
    }

    // And no reading text falls through the floor, headings included.
    expect(sizes.body, `${surface} body text`).toBeGreaterThanOrEqual(READING_FLOOR);

    const small = await undersizedTargets(page, TARGET_FLOOR);
    expect(small, `${surface} has targets under ${TARGET_FLOOR}px`).toEqual([]);

    await page.screenshot({ path: info.outputPath(`${surface}.png`), fullPage: true });
  }

  // One h1 size across the cockpit: the research pages and the manuscript workspace agree.
  const measured = [...h1Sizes.values()];
  expect(new Set(measured).size, `h1 sizes were ${JSON.stringify([...h1Sizes])}`).toBe(1);
  expect(measured[0]).toBeGreaterThan(READING_FLOOR);

  expect(errors).toEqual([]);
});

test('a compact surface stays dense without going under either floor', async ({
  page,
  request,
}, info) => {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`Typeset table ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await page.waitForURL(/\/projects\/[^/?#]+/);
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  await page.goto(`${workspace}/corpus`);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  /*
   * A new project has no works and no queue, so the two things compact density used to
   * break are measured on probes mounted into the live page — the same markup `DataTable`
   * and `IconButton` emit, inside the same `data-density="compact"` wrapper — and taken
   * away again. Seeding a corpus would test the seed; this tests the stylesheet.
   */
  const measured = await page.evaluate(() => {
    const host = document.createElement('div');
    host.setAttribute('data-density', 'compact');
    host.innerHTML =
      '<table class="rh-web-table"><tbody><tr><td id="rh-cell-probe">A traffic classifier study</td></tr></tbody></table>' +
      '<button id="rh-target-probe" type="button" class="rh-icon-button rh-icon-button--sm rh-button--ghost"></button>';
    document.body.appendChild(host);
    const cell = host.querySelector('#rh-cell-probe') as HTMLElement;
    const target = host.querySelector('#rh-target-probe') as HTMLElement;
    const box = target.getBoundingClientRect();
    const out = {
      cell: Number.parseFloat(getComputedStyle(cell).fontSize),
      body: Number.parseFloat(getComputedStyle(document.body).fontSize),
      target: { width: box.width, height: box.height },
    };
    host.remove();
    return out;
  });

  expect(
    measured.cell,
    `a compact table cell computed to ${measured.cell}px`,
  ).toBeGreaterThanOrEqual(READING_FLOOR);
  // Still a queue, not prose: dense text, above the floor rather than through it.
  expect(measured.cell).toBeLessThan(measured.body);

  expect(
    Math.min(measured.target.width, measured.target.height),
    `a compact icon button measured ${measured.target.width}x${measured.target.height}`,
  ).toBeGreaterThanOrEqual(TARGET_FLOOR);

  await page.screenshot({ path: info.outputPath('corpus-compact.png'), fullPage: true });
});
