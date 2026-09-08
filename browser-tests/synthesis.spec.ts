/**
 * The synthesis matrix, drawn in a real browser against the real daemon.
 *
 * `/__test__/synthesis-grid` builds a project through the daemon's own services until one
 * matrix holds every state of a cell the grid has to draw: a reading read from an accepted
 * span, a reading read from a numeric span that keeps its metric and unit, a reading with no
 * evidence recorded behind it, and cells nobody has read at all — across two works, so a
 * column carries two different readings. What is asserted below is a grid composed from real
 * accepted state, not from a fixture.
 *
 * The properties it has to keep are the ones the second critique scored against this page.
 * A cell states in words whether it was recorded — never a tint, never an empty box. A
 * recorded cell reaches the exact span it rests on. The field to read down a column is
 * offered rather than remembered: the picker lists the matrix's own fields before a
 * character is typed. And the grid keeps its width inside its own scroll region, so the
 * document never scrolls sideways at either width the suite runs.
 *
 * The second case is the one a unit test cannot settle. `/__test__/large-matrix` builds a
 * matrix over the thousand-work corpus the resilience suite seeds, which is far past the
 * few hundred works a real project reaches and past the 200 the daemon answers whole. How
 * long that takes to draw, how much of it is in the DOM, whether the far end of it is
 * reachable and whether a column keeps its name while a thousand rows pass under it are all
 * questions about a real browser against the real daemon, and only one of them has an
 * answer a jsdom window could give.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { axeViolations } from './axe';

/** How many works the long matrix is built over. Far past the few hundred a project has. */
const LARGE_WORKS = 1000;

/**
 * The same budget the corpus's own thousand-work case holds itself to, for the same reason:
 * the render is the measurement, and it sits behind a real capability read over a thousand
 * durable works and a cold Chromium. Generous, and still a bound.
 */
const RENDER_BUDGET_MS = 30_000;

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** Every leaf element inside the page frame whose whole text is a number. */
async function bareNumbers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const node of Array.from(document.querySelectorAll('.rh-full-page *'))) {
      if (!(node instanceof HTMLElement) || node.children.length > 0) continue;
      if ((node.textContent ?? '').trim().match(/^\d+([.,]\d+)?%?$/)) found.push(node.outerHTML);
    }
    return found;
  });
}

async function auditPage(page: Page, name: string): Promise<void> {
  expect(await axeViolations(page), `${name} must have no accessibility violations`).toEqual([]);
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, `${name} must not overflow horizontally`).toBeTruthy();
}

test('the matrix is a grid a property can be read down', async ({ page, request }, info) => {
  // Seeding ingests, parses and interrogates a paper before the page is opened.
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/synthesis-grid', { timeout: 90_000 });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(`${project.workspace_url}/synthesis`);
  await expect(page.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeVisible();

  // -- the grid: the matrix's own works against its own fields ---------------
  await expect(page.getByRole('columnheader', { name: 'Work' })).toBeVisible();
  const columns = await page.getByRole('columnheader').allInnerTexts();
  expect(
    columns.map((text) => text.trim()),
    'the column heads are the vocabulary’s words, in the matrix’s declared order',
  ).toEqual(['Work', 'Dataset', 'Metric result', 'Tokenization']);
  await expect(page.getByRole('rowheader')).toHaveCount(2);
  // A column two works read differently is the disagreement a matrix is opened to find.
  await expect(page.getByText('cicids2017', { exact: true })).toBeVisible();
  await expect(page.getByText('unsw_nb15', { exact: true })).toBeVisible();
  // Every cell nobody has read says so in words, never in a tint or an empty box.
  await expect(page.getByText('Not recorded', { exact: true })).toHaveCount(3);
  await expect(page.getByText(/An empty cell means/)).toBeVisible();
  expect(await bareNumbers(page), 'no number stands on its own on the synthesis page').toEqual([]);
  await page.screenshot({ path: info.outputPath('synthesis-grid.png'), fullPage: true });

  // -- the grid scrolls inside its own region, never the document ------------
  const region = await page.evaluate(() => {
    const area = document.querySelector('.rh-web-matrix .rh-scroll-area');
    if (!(area instanceof HTMLElement)) return null;
    return {
      overflowX: getComputedStyle(area).overflowX,
      scrolls: area.scrollWidth > area.clientWidth,
    };
  });
  expect(region?.overflowX, 'the grid keeps its width inside its own scroll region').toBe('auto');
  if (region?.scrolls) {
    await expect(
      page.getByRole('region', { name: 'The Traffic representation matrix' }),
      'a grid that scrolls is a named, keyboard-reachable region',
    ).toBeVisible();
  }
  await auditPage(page, 'the synthesis page');

  // -- a recorded cell reaches the span it rests on --------------------------
  await page.getByText('reported', { exact: true }).click();
  await expect(page.getByText('Read from 1 accepted evidence span.')).toBeVisible();
  const span = page.getByRole('link', { name: /metric result/ });
  await expect(span).toBeVisible();
  expect(await span.getAttribute('href')).toContain('/evidence/');
  // The number keeps the metric and the unit it was recorded under (PRODUCT §12), and it
  // is on the page once: the cell carries it, so the opened span does not repeat it.
  await expect(page.getByText('F1 94.32 percent')).toHaveCount(1);
  await page.screenshot({ path: info.outputPath('synthesis-evidence.png'), fullPage: true });
  await auditPage(page, 'the synthesis page with a cell opened');

  // -- the field is offered, never remembered -------------------------------
  const picker = page.getByRole('combobox', { name: 'Read a field down its column' });
  await expect(picker).toHaveValue('');
  await picker.click();
  const offered = await page.getByRole('option').allInnerTexts();
  expect(
    offered.map((text) => text.split('\n')[0]!.trim()),
    'every field this matrix declares is offered before a character is typed',
  ).toEqual(['Dataset', 'Metric result', 'Tokenization']);

  await page.getByRole('option', { name: /Tokenization/ }).click();
  await expect(page.getByRole('columnheader', { name: 'Tokenization' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  await expect(
    page.getByText(
      'Tokenization — No work in this matrix has been read for it yet, so there is nothing to read across it.',
    ),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath('synthesis-column.png'), fullPage: true });
  await auditPage(page, 'the synthesis page with a column read down');

  expect(errors).toEqual([]);
});

test('a matrix over a thousand works draws a window, not a thousand rows', async ({
  page,
  request,
}, info) => {
  // Seeding a thousand works and the matrix over them durably is minutes of fsync, and the
  // render measurement sits behind it.
  test.setTimeout(900_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  // Generous: the registry this lists may already hold a thousand-work workspace, and the
  // host opens each project to say whether it is available.
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible({
    timeout: 180_000,
  });
  const seeded = await request.post(`/__test__/large-matrix?works=${LARGE_WORKS}`, {
    timeout: 900_000,
  });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();
  expect(project.works).toBe(String(LARGE_WORKS));

  // -- first paint, and only a window of the matrix in the DOM ---------------
  const started = Date.now();
  await page.goto(project.synthesis_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeVisible();
  const grid = page.getByRole('grid', { name: 'The Traffic representation at scale matrix' });
  await expect(grid).toBeVisible({ timeout: RENDER_BUDGET_MS });
  await expect(grid.getByRole('rowheader').first()).toBeVisible({ timeout: RENDER_BUDGET_MS });
  const elapsed = Date.now() - started;

  const mounted = await grid.getByRole('row').count();
  console.log(
    `[synthesis/${info.project.name}] a matrix over ${LARGE_WORKS} works: first row visible ` +
      `in ${elapsed}ms, ${mounted} of ${LARGE_WORKS} rows in the DOM`,
  );
  expect(elapsed, `a matrix over ${LARGE_WORKS} works took ${elapsed}ms to draw`).toBeLessThan(
    RENDER_BUDGET_MS,
  );
  // Bounded, and bounded far below the matrix. The exact number is the window plus its
  // overscan and the heading row, and is not the contract; that there is a bound is.
  expect(mounted).toBeGreaterThan(1);
  expect(mounted).toBeLessThan(40);
  // What is in the DOM is a window; what the grid says it is, is the whole matrix.
  await expect(grid).toHaveAttribute('aria-rowcount', String(LARGE_WORKS + 1));
  await expect(
    page.getByText(`200 of ${LARGE_WORKS} works loaded.`, { exact: false }),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath('synthesis-large-matrix.png'), fullPage: false });
  await auditPage(page, 'the synthesis page over a thousand works');

  // -- the far end of the matrix is reachable, a page at a time --------------
  const window_ = page.getByRole('rowgroup', {
    name: 'Works in the Traffic representation at scale matrix',
  });
  await window_.focus();
  // Each End lands at the end of what is loaded, which is what asks for the next page; the
  // matrix is five pages long, so this presses until the last work of the corpus is drawn.
  await expect(async () => {
    await page.keyboard.press('End');
    await expect(
      page.getByRole('rowheader', { name: new RegExp(`Synthetic corpus study ${LARGE_WORKS}`) }),
    ).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 240_000 });
  await expect(page.getByText(`All ${LARGE_WORKS} works are loaded.`)).toBeVisible();
  expect(
    await grid.getByRole('row').count(),
    'the far end of the matrix is a window too',
  ).toBeLessThan(40);

  // -- the heading strip follows the rows sideways ---------------------------
  // The strip stands outside the window, so nothing but this keeps a cell under its own
  // column head once a matrix is wider than the pane it is read in.
  await window_.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
  });
  const aligned = await page.evaluate(() => {
    const strip = document.querySelector('.rh-web-matrix__strip');
    const rows = document.querySelector('.rh-web-matrix__window');
    if (!(strip instanceof HTMLElement) || !(rows instanceof HTMLElement)) return null;
    return { strip: strip.scrollLeft, rows: rows.scrollLeft, scrolled: rows.scrollLeft > 0 };
  });
  expect(aligned, 'the windowed grid draws a heading strip and a window').not.toBeNull();
  expect(aligned?.strip, 'the column heads follow the rows sideways').toBe(aligned?.rows);

  // -- the column head is still there to read the field under ----------------
  // A heading that scrolled away with the rows would be exactly the recall this page exists
  // to remove: at row nine hundred, a reading still has to say which field it is a reading of.
  await expect(page.getByRole('columnheader', { name: 'Tokenization' })).toBeInViewport();
  await expect(page.getByRole('columnheader', { name: 'Work' })).toBeInViewport();
  await page.screenshot({ path: info.outputPath('synthesis-large-matrix-end.png'), fullPage: false });

  // -- and the page still does not run off the side, at either width ---------
  await auditPage(page, 'the synthesis page at the end of a thousand-work matrix');
  expect(errors).toEqual([]);
});
