/**
 * The Evidence index in a real browser, against the real daemon.
 *
 * This is the page the third critique's first P1 asked for: the product's largest body of
 * accepted state, browsable, under "The record" between Corpus and Claims. So what is
 * asserted here is that it keeps the pattern the other record pages keep — the work before
 * the size of the record, rows across shared columns, the questions as the controls that
 * narrow them, the narrowing the daemon's rather than the browser's — and that a row leads
 * to the reading's own page, which is the only action this page offers.
 *
 * The same file covers the minor observation from the same critique: an unknown URL used to
 * render the Overview silently, so a stale bookmark showed a plausible wrong page.
 *
 * The find is exercised in the unit suite over a list long enough to narrow; here it is the
 * empty state it can produce that matters, because that state is the one a researcher meets
 * with the whole record hidden behind it.
 *
 * `/__test__/evidence-record` builds the state through the daemon's own services: a paper
 * ingested and parsed, three candidates accepted through the review queue, one Claim resting
 * on the first of them, and one reading marked stale the way the staleness pass marks one.
 */
import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/**
 * Every number on the page that nothing labels.
 *
 * A `<dd>` answers the `<dt>` beside it and a cell answers its column header; those are the
 * comparative readings the row exists for. What the pattern forbids is the other thing — a
 * count rendered as a figure with nothing around it — so those three tags are the only
 * exemption, and everything else that is only digits is a defect.
 */
async function bareNumbers(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const node of Array.from(document.querySelectorAll('.rh-full-page *'))) {
      if (!(node instanceof HTMLElement) || node.children.length > 0) continue;
      // A quotation is the source's own words. When a source's words are "94.32" — an
      // exact metric span, which is most of what this record holds — printing it is
      // quoting, not the stat tile the pattern forbids.
      if (['DD', 'TD', 'TH', 'BLOCKQUOTE'].includes(node.tagName)) continue;
      if ((node.textContent ?? '').trim().match(/^\d+([.,]\d+)?%?$/)) found.push(node.outerHTML);
    }
    return found;
  });
}

async function auditPage(page: import('@playwright/test').Page, name: string): Promise<void> {
  expect(await axeViolations(page), `${name} must have no accessibility violations`).toEqual([]);
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, `${name} must not overflow horizontally`).toBeTruthy();
}

/** Redeem a bootstrap nonce so this browser holds the application token. */
async function signIn(
  page: import('@playwright/test').Page,
  request: import('@playwright/test').APIRequestContext,
): Promise<void> {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible({
    timeout: 180_000,
  });
}

async function recordOf(request: import('@playwright/test').APIRequestContext) {
  const seeded = await request.post('/__test__/evidence-record', { timeout: 300_000 });
  expect(seeded.ok()).toBeTruthy();
  return (await seeded.json()) as {
    project_id: string;
    name: string;
    workspace_url: string;
    evidence_url: string;
  };
}

/** Below the shell's breakpoint the rail is a drawer, so it has to be opened first. */
async function openRail(page: import('@playwright/test').Page): Promise<void> {
  const opener = page.getByRole('button', { name: 'Project navigation', exact: true });
  if (await opener.isVisible()) await opener.click();
}

/** This page's own find. The rail has a search box too, so this one is named. */
function findEvidence(page: import('@playwright/test').Page) {
  return page.getByRole('searchbox', { name: /Find evidence/ });
}

/** The live line that counts the record; the page has more than one polite region. */
function recordCount(page: import('@playwright/test').Page) {
  return page
    .getByRole('region', { name: 'Everything this project has accepted' })
    .getByRole('status');
}

test('the evidence index names the readings that need a researcher before the size of the record', async ({
  page,
  request,
}, info) => {
  // Ingesting and parsing a paper and accepting three candidates sits in front of the
  // assertions.
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const record = await recordOf(request);
  await page.goto(record.evidence_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Evidence' })).toBeVisible();

  // The daemon's groups, in the daemon's order: what has decayed before what landed
  // nowhere. One reading went stale; of the other two, one is cited by a claim and one is
  // not — and the stale one is named only once, by the first thing wrong with it.
  const lead = page.locator('.rh-web-evidence__attention');
  const decayed = lead.getByText('1 piece of evidence went stale when its source changed');
  await expect(decayed).toBeVisible();
  await expect(lead.getByText('1 piece of evidence is cited by no claim')).toBeVisible();
  // Groups this size name every reading they count: a cap sentence is neither a reading nor
  // a link, and a reader who wanted it would have to go and find it.
  await expect(lead.getByText(/more (is|are) in the list below\./)).toHaveCount(0);

  // A named reading leads to itself, and it is named by the field it answers and the work
  // it was read from rather than by `E0002 · W0001`.
  const named = lead.getByRole('link').first();
  await expect(named).toHaveAttribute('href', /\/evidence\/E\d{4}$/);
  await expect(named).toHaveText(/·/);
  await expect(named).toContainText('Deep Representations for Encrypted Network Traffic');

  // The size of the record is read after the work, and the work is in the first screenful.
  const count = recordCount(page);
  await expect(count).toHaveText('3 pieces of evidence.');
  const decayedBox = (await decayed.boundingBox())!;
  const countBox = (await count.boundingBox())!;
  expect(decayedBox.y, 'what needs a researcher is in the first screenful').toBeLessThan(
    page.viewportSize()!.height,
  );
  expect(
    decayedBox.y,
    'what needs a researcher is read before the size of the record',
  ).toBeLessThan(countBox.y);
  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);

  // The rows are the instrument, and the row is where the questions are answered.
  await expect(page.locator('.rh-web-evidence__head .rh-web-evidence__column')).toHaveText([
    'Evidence',
    'Type',
    'Strength',
    'Origin',
    'Cited by',
    'Accepted',
  ]);

  // One row, read across. Each cell carries its own name for a screen reader that only ever
  // has a window of the list to read, and the quoted span is on the row rather than a press
  // away, because the span is what a reading is.
  const first = page.locator('.rh-web-evidence__row').first();
  const cell = (index: number) => first.locator('.rh-web-evidence__cell').nth(index);
  await expect(first.locator('blockquote')).not.toBeEmpty();
  for (const [index, name] of [
    [1, 'Evidence type'],
    [2, 'Strength'],
    [3, 'Epistemic origin'],
    [4, 'Claims citing it'],
    [5, 'Accepted'],
  ] as const) {
    await expect(cell(index), `the row names its ${name}`).toContainText(name);
  }
  // The vocabularies are printed as the product says them, never as the wire spells them.
  await expect(cell(3)).not.toContainText('_');
  // What rests on a reading is said in words: the claim's own statement, or "Nothing yet".
  await expect(page.getByText('Nothing yet').first()).toBeVisible();

  await auditPage(page, 'the evidence index');
  await page.screenshot({ path: info.outputPath('evidence-needs-a-researcher.png'), fullPage: false });
  expect(errors).toEqual([]);
});

/**
 * The questions a researcher brings, against a real record.
 *
 * `evidence.list` composes them — what went stale, what no claim cites, what came in lately
 * — counts each over the whole record, and answers with the rows that answer the question.
 * So what is asserted here is that pressing one narrows the list to exactly what the daemon
 * counted, that the lead and the counts stay whole while it is narrowed, and that the
 * browser's own find still works inside it.
 */
test('the questions the record can be asked are the controls that narrow it', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const record = await recordOf(request);
  await page.goto(record.evidence_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Evidence' })).toBeVisible();

  const bar = page.getByRole('group', { name: 'Ask the record a question' });
  const everything = bar.getByRole('button', { name: 'Everything accepted (3)' });
  const wentStale = bar.getByRole('button', { name: 'Went stale (1)' });
  const uncited = bar.getByRole('button', { name: 'Cited by no claim (1)' });
  await expect(everything).toHaveAttribute('aria-pressed', 'true');
  await expect(wentStale).toBeVisible();
  await expect(uncited).toBeVisible();

  const rows = page.locator('.rh-web-evidence__row');
  await expect(rows).toHaveCount(3);

  // The one the daemon counted, and only that one. It says "Nothing yet" under "Claims
  // citing it", which is the question, answered on the row — and the reading a claim does
  // rest on is gone from the list.
  await uncited.click();
  await expect(recordCount(page)).toHaveText(
    '1 of 3 pieces of evidence is cited by no claim.',
  );
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator('.rh-web-evidence__cell').nth(4)).toContainText(
    'Nothing yet',
  );
  await expect(uncited).toHaveAttribute('aria-pressed', 'true');
  await expect(everything).toHaveAttribute('aria-pressed', 'false');

  // The lead is about the record, so it does not move; neither do the counts on the
  // controls, which are over the whole of it.
  await expect(
    page
      .locator('.rh-web-evidence__attention')
      .getByText('1 piece of evidence went stale when its source changed'),
  ).toBeVisible();
  await expect(wentStale).toBeVisible();
  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);

  // The find is the one question about the text on screen rather than about the science, so
  // it stays in the browser — and it says which set it is narrowing.
  await findEvidence(page).fill('no reading in this record says this');
  await expect(page.getByText('Nothing matches this find')).toBeVisible();
  await expect(page.getByText(/The find only hides/)).toBeVisible();
  await page.getByRole('button', { name: 'Clear the find' }).click();
  await expect(recordCount(page)).toHaveText(
    '1 of 3 pieces of evidence is cited by no claim.',
  );

  await auditPage(page, 'the evidence index narrowed to one question');
  await page.screenshot({ path: info.outputPath('evidence-one-question.png'), fullPage: false });

  // A question narrows and nothing else: pressing the chosen one again is the way back.
  await uncited.click();
  await expect(recordCount(page)).toHaveText('3 pieces of evidence.');
  await expect(rows).toHaveCount(3);
  expect(errors).toEqual([]);
});

test('a row opens the reading at the exact span it was accepted from', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const record = await recordOf(request);
  await page.goto(record.evidence_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Evidence' })).toBeVisible();

  const first = page.locator('.rh-web-evidence__row').first();
  const quote = (await first.locator('blockquote').innerText()).trim();
  await first.locator('.rh-web-evidence__name').click();

  // The evidence page: the same span, with the epistemics and the source behind it.
  await page.waitForURL(/\/evidence\/E\d{4}$/);
  await expect(page.locator('.rh-web-quote')).toContainText(quote.slice(0, 40));
  await expect(page.getByRole('link', { name: 'Open the source file' })).toBeVisible();

  await auditPage(page, 'one accepted reading');
  await page.screenshot({ path: info.outputPath('evidence-one-reading.png'), fullPage: false });
  expect(errors).toEqual([]);
});

test('the rail lists Evidence under The record, between Corpus and Claims', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const record = await recordOf(request);
  await page.goto(record.workspace_url);
  // The shell first: until the workspace's own main landmark is up, the rail — and the
  // button that opens it below the shell's breakpoint — is not on the page to be found.
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();
  await openRail(page);

  const group = page.getByRole('list', { name: 'The record' });
  await expect(group).toBeVisible();
  await expect(group.locator('.rh-project-rail__nav-label')).toHaveText([
    'Corpus',
    'Evidence',
    'Claims',
    'Questions',
    'Taxonomy',
  ]);

  // And it goes where it says it goes.
  await page.getByRole('link', { name: /Evidence/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Evidence' })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`${record.workspace_url}/evidence$`));

  await page.screenshot({ path: info.outputPath('evidence-in-the-rail.png'), fullPage: false });
  expect(errors).toEqual([]);
});

test('an address the cockpit serves no page at says so instead of showing another page', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const record = await recordOf(request);
  await page.goto(`${record.workspace_url}/evidenc`);

  // Not the Overview wearing someone else's URL: the page says what is true, keeps the
  // frame, and quotes the address back so a typo can be seen.
  await expect(
    page.getByRole('heading', { level: 1, name: 'There is no page at this address' }),
  ).toBeVisible();
  // The address alone: the heading above already states the absence, and stating it again
  // inside the card is one absence said twice (wave three's ruling).
  await expect(page.getByText(`${record.workspace_url}/evidenc`, { exact: true })).toBeVisible();
  await expect(page.getByText(/Nothing is served at/)).toHaveCount(0);
  await expect(page.getByText(/Nothing about the project has changed/)).toBeVisible();

  await auditPage(page, 'an unknown address');
  await page.screenshot({ path: info.outputPath('evidence-no-such-page.png'), fullPage: false });

  // One way on, and it works.
  await page.getByRole('link', { name: 'Go to the Overview' }).click();
  await expect(page).toHaveURL(new RegExp(`${record.workspace_url}/overview$`));
  expect(errors).toEqual([]);
});
