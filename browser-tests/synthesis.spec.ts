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
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { axeViolations } from './axe';

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
