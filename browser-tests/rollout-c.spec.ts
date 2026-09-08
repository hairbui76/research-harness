/**
 * The Corpus page in a real browser, against the real daemon.
 *
 * The Overview's pattern says a research page opens with what needs a researcher and reads
 * the size of the project after it. The corpus is where that is hardest to hold: it is the
 * one screen whose length nothing bounds, its list is windowed, and the list itself is
 * genuinely comparative — whether a source can be read from, what has been accepted from
 * it, what cites it, when it came in — read by running an eye down shared columns. So the
 * lead names the work, the rows answer the questions a researcher brings, and the questions
 * themselves are the controls that narrow the list. What is asserted below is that all of
 * it is true at once, and that the narrowing is the daemon's rather than the browser's.
 *
 * `/__test__/corpus-readiness` builds the state through the daemon's own services: a paper
 * ingested and parsed with nothing accepted from it, four more sources whose one file has
 * never been parsed, and — on request — the same paper with a candidate accepted against
 * it, so a corpus that needs nothing can be photographed too.
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
 * comparative readings the works table exists for. What the pattern forbids is the other
 * thing — a count rendered as a figure with nothing around it — so those three tags are the
 * only exemption, and everything else that is only digits is a defect.
 */
async function bareNumbers(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => {
    const found: string[] = [];
    for (const node of Array.from(document.querySelectorAll('.rh-full-page *'))) {
      if (!(node instanceof HTMLElement) || node.children.length > 0) continue;
      if (['DD', 'TD', 'TH'].includes(node.tagName)) continue;
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
): Promise<string> {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible({
    timeout: 180_000,
  });
  return parent as string;
}

async function corpusOf(
  request: import('@playwright/test').APIRequestContext,
  needsAResearcher: boolean,
) {
  const seeded = await request.post(
    `/__test__/corpus-readiness?needs_a_researcher=${needsAResearcher}`,
    { timeout: 300_000 },
  );
  expect(seeded.ok()).toBeTruthy();
  return (await seeded.json()) as { project_id: string; name: string; corpus_url: string };
}

/** The corpus page's own find. The rail has a search box too, so this one is named. */
function findAWork(page: import('@playwright/test').Page) {
  return page.getByRole('searchbox', { name: /Find a work/ });
}

test('the corpus names the sources that need a researcher before it says how much it holds', async ({
  page,
  request,
}, info) => {
  // Ingesting and parsing a paper sits in front of the assertions.
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const corpus = await corpusOf(request, true);
  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  // The daemon's groups, in the daemon's order: what cannot be read from at all comes
  // before what can be read from and has not been.
  const lead = page.locator('.rh-web-corpus__attention');
  await expect(lead.getByText('4 works have no readable text yet')).toBeVisible();
  await expect(lead.getByText('1 work has nothing accepted from it yet')).toBeVisible();
  // A group this size names every work it counts: a cap sentence is neither a work nor a
  // link, and a reader who wanted that work would have to go and find it.
  await expect(lead.getByText(/more (is|are) in the list below\./)).toHaveCount(0);
  await expect(lead.getByRole('link')).toHaveCount(5);

  // A named work leads to itself, never back to the corpus the reader is standing on.
  const named = lead.getByRole('link').first();
  await expect(named).toHaveAttribute('href', /\/corpus\/W\d{4}$/);
  const namedId = (await named.getAttribute('href'))!.split('/').pop()!;

  // The size of the project is read after the work, and the work is in the first screenful.
  const needed = lead.getByText('4 works have no readable text yet');
  const count = page.getByRole('status').filter({ hasText: '5 works.' });
  await expect(count).toBeVisible();
  const neededBox = (await needed.boundingBox())!;
  const countBox = (await count.boundingBox())!;
  expect(neededBox.y, 'what needs a researcher is in the first screenful').toBeLessThan(
    page.viewportSize()!.height,
  );
  expect(
    neededBox.y,
    'what needs a researcher is read before the size of the corpus',
  ).toBeLessThan(countBox.y);
  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);

  // The works stay the instrument, and the row is where the questions are answered: the
  // columns that used to be a stack of labels per card are one strip over a thousand rows.
  const works = page.getByRole('region', { name: 'Every work in the corpus' });
  await expect(page.locator('.rh-web-corpus__head .rh-web-corpus__column')).toHaveText([
    'Work',
    'Screening',
    'Readable',
    'Accepted',
    'Cited by',
    'Came in',
  ]);

  // One row, read across. Nothing here is opened: the four facts a corpus is asked about
  // are on the row, and each cell carries its own name for a screen reader that only ever
  // has a window of the list to read.
  const first = page.locator('.rh-web-corpus__row').first();
  const cell = (index: number) => first.locator('.rh-web-corpus__cell').nth(index);
  await expect(cell(0).getByRole('link').first()).toBeVisible();
  for (const [index, name] of [
    [1, 'Screening state'],
    [2, 'Readable text'],
    [3, 'Accepted evidence'],
    [4, 'Claims citing it'],
    [5, 'Came into the corpus'],
  ] as const) {
    await expect(cell(index), `the row names its ${name}`).toContainText(name);
  }
  await expect(cell(2), 'the paper the lead named has been parsed').toContainText('yes');
  await expect(cell(3), 'and nothing has been accepted from it').toContainText('0');

  // Its files are one press away, inside the row: reaching them never unmounts the list.
  const files = first.getByRole('button', { name: /file/ });
  await expect(files).toHaveAttribute('aria-expanded', 'false');
  await files.click();
  await expect(first.getByRole('columnheader', { name: 'Parsed' })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Works in the corpus' })).toBeVisible();
  await files.click();

  // The work the lead named is reachable through the find without scrolling to it. Its own
  // id is the query, because a title or a year can be a substring of another work's id and
  // the find matches over both.
  await findAWork(page).fill(namedId);
  await expect(page.getByRole('status').filter({ hasText: 'Showing 1 of 5 works.' })).toBeVisible();
  await expect(works.getByRole('link', { name: namedId })).toBeVisible();
  await findAWork(page).fill('');
  await expect(count).toBeVisible();

  await auditPage(page, 'the corpus');
  await page.screenshot({ path: info.outputPath('corpus-needs-a-researcher.png'), fullPage: false });
  expect(errors).toEqual([]);
});

/**
 * The questions a researcher brings, against a real corpus.
 *
 * `work.list` composes them — which works cannot be read from yet, which have nothing
 * accepted, which came in lately — counts each over the whole corpus, and answers with the
 * works that answer the question. So what is asserted here is that pressing one narrows the
 * list to exactly what the daemon counted, that the lead and the counts stay whole while it
 * is narrowed, and that the browser's own find still works inside it.
 */
test('the questions the corpus can be asked are the controls that narrow it', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const corpus = await corpusOf(request, true);
  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  const bar = page.getByRole('group', { name: 'Ask the corpus a question' });
  const every = bar.getByRole('button', { name: 'Every work (5)' });
  const unparsed = bar.getByRole('button', { name: 'No readable text (4)' });
  const unread = bar.getByRole('button', { name: 'Nothing accepted (1)' });
  await expect(every).toHaveAttribute('aria-pressed', 'true');
  await expect(unparsed).toBeVisible();
  await expect(unread).toBeVisible();

  const rows = page.locator('.rh-web-corpus__row');
  await expect(rows).toHaveCount(5);

  // The four the daemon counted, and only those. Every one of them says "no" under
  // Readable text, which is the question, answered on the row.
  await unparsed.click();
  await expect(
    page.getByRole('status').filter({ hasText: '4 of 5 works have no readable text yet.' }),
  ).toBeVisible();
  await expect(rows).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    await expect(rows.nth(index).locator('.rh-web-corpus__cell').nth(2)).toContainText('no');
  }
  await expect(unparsed).toHaveAttribute('aria-pressed', 'true');
  await expect(every).toHaveAttribute('aria-pressed', 'false');

  // The lead is about the corpus, so it does not move; neither do the counts on the
  // controls, which are over the whole of it.
  await expect(
    page.locator('.rh-web-corpus__attention').getByText('1 work has nothing accepted from it yet'),
  ).toBeVisible();
  await expect(unread).toBeVisible();
  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);

  // The find is the one question about the text on screen rather than about the science, so
  // it stays in the browser — and it says which set it is narrowing.
  const inside = await rows.first().getByRole('link', { name: /^W\d{4}$/ }).innerText();
  await findAWork(page).fill(inside);
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: '4 of 5 works have no readable text yet. Showing 1 of them.' }),
  ).toBeVisible();
  await expect(rows).toHaveCount(1);
  await findAWork(page).fill('');

  await auditPage(page, 'the corpus narrowed to one question');
  await page.screenshot({ path: info.outputPath('corpus-one-question.png'), fullPage: false });

  // A question narrows and nothing else: pressing the chosen one again is the way back.
  await unparsed.click();
  await expect(page.getByRole('status').filter({ hasText: '5 works.' })).toBeVisible();
  await expect(rows).toHaveCount(5);
  expect(errors).toEqual([]);
});

test('a corpus that needs nothing teaches what would put a source there', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const corpus = await corpusOf(request, false);
  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  await expect(page.getByText('Nothing among these sources needs a researcher')).toBeVisible();
  await expect(page.getByText(/no file has been attached to it/)).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open the conversation to attach another source' }),
  ).toBeVisible();
  // The works are still there, and still say how many of them there are.
  await expect(page.getByRole('status').filter({ hasText: '1 works.' })).toBeVisible();

  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'a corpus that needs nothing');
  await page.screenshot({ path: info.outputPath('corpus-nothing-needed.png'), fullPage: false });
  expect(errors).toEqual([]);
});

test('a project with no corpus at all keeps its frame and offers the way in', async ({
  page,
  request,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const parent = await signIn(page, request);
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`New corpus ${info.project.name}`);
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

  // The frame survives, and the one empty state a corpus with nothing in it can have says
  // what the corpus is for and how a source enters it.
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();
  await expect(page.getByText('No works in the corpus yet')).toBeVisible();
  await expect(page.getByText(/whether a file has a stored parse/)).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open the conversation to attach a source' }),
  ).toBeVisible();

  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'a corpus with nothing in it');
  await page.screenshot({ path: info.outputPath('corpus-empty.png'), fullPage: false });
  expect(errors).toEqual([]);
});

/**
 * The columns as the orders the corpus can be read in.
 *
 * "Accepted" and "Cited by" were names over a thousand rows and nothing else: the only way
 * to find the work the most has been accepted from was to scroll. Each column that can be
 * put in order of is now the control that asks for that order, and it asks the daemon —
 * `work.list` answers the whole corpus in one read while the page keeps a window of it, so
 * a comparator here would order the mounted rows and call them the corpus.
 *
 * `/__test__/corpus-ordered` is what makes that testable: one parsed paper with a candidate
 * accepted against it, and sixty synthetic sources behind it. The paper is `W0001`, so it
 * leads the corpus's own order too — which is why the ascending half of each assertion is
 * the one that matters. It is not merely last there; it is outside the window.
 *
 * Below the stacking breakpoint there are no columns to head, so the same orders are one
 * labelled select instead — a strip reading "Work  Accepted ↓  Cited by  Came in" over
 * stacked cards is a table head with no table under it. This test runs at both widths and
 * asks for each order through whichever control the width offers; every assertion under it
 * is about the corpus, and is the same at both.
 */
test('the corpus columns are the orders it can be read in, and the daemon takes them', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const seeded = await request.post('/__test__/corpus-ordered', { timeout: 300_000 });
  expect(seeded.ok()).toBeTruthy();
  const corpus = (await seeded.json()) as { corpus_url: string; works: string };
  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  const count = page.getByRole('status').filter({ hasText: `${corpus.works} works.` });
  await expect(count).toBeVisible();
  const rows = page.locator('.rh-web-corpus__row');
  // Selected by class rather than by role, because one of the two controls is hidden at any
  // width and a hidden element is in no accessibility tree. `aria-sort` is still asserted
  // on the strip at both widths: it is the state, and the state is one.
  const accepted = page.locator('.rh-web-corpus__column').filter({ hasText: 'Accepted' }).first();
  const strip = page.locator('.rh-web-corpus__head-table');
  const select = page.getByRole('combobox', { name: 'Order by' });
  const withEvidence = rows.filter({ has: page.getByRole('link', { name: 'W0001' }) });

  /*
   * Exactly one control for the corpus's order, chosen by the width.
   *
   * Both are in the page and a container query hides one outright, so a screen reader is
   * never offered the order twice — which is the whole reason the narrow answer is a second
   * control rather than the same strip wrapped.
   */
  const wide = await strip.isVisible();
  await expect(select).toBeVisible({ visible: !wide });
  expect(
    await strip.getByRole('columnheader').count(),
    'the columns this width exposes',
  ).toBe(wide ? 6 : 0);

  /** Ask for one order, through whichever control this width offers. */
  const readBy = async (
    column: string,
    field: string,
    descending: boolean | null,
  ): Promise<void> => {
    const wanted = descending === null ? 'none' : descending ? 'descending' : 'ascending';
    const head = page.locator('.rh-web-corpus__column').filter({ hasText: column }).first();
    if (!wide) {
      await select.selectOption(descending === null ? '' : `${field}:${descending ? 'desc' : 'asc'}`);
      return;
    }
    // The head cycles: the useful end of the column, the other end, then the corpus's own
    // order. Pressing until it reports the wanted state asks for exactly that order and
    // never more than the cycle is long.
    for (let press = 0; press < 3; press += 1) {
      if ((await head.getAttribute('aria-sort')) === wanted) return;
      await page.getByRole('columnheader', { name: column }).getByRole('button').click();
    }
  };

  // Nothing is ordered until something asks: the corpus arrives in the daemon's own order,
  // and the strip says so on every column that could change it.
  await expect(accepted).toHaveAttribute('aria-sort', 'none');
  await expect(count).toHaveText(`${corpus.works} works.`);

  // Most accepted evidence first. The one work anything has been accepted from leads, and
  // the sentence the corpus is counted in says how it is being read.
  await readBy('Accepted', 'evidence', true);
  await expect(
    page.getByRole('status').filter({ hasText: 'Most accepted evidence first.' }),
  ).toBeVisible();
  await expect(accepted).toHaveAttribute('aria-sort', 'descending');
  await expect(rows.first().getByRole('link', { name: 'W0001' })).toBeVisible();
  await expect(rows.first().locator('.rh-web-corpus__cell').nth(3)).toContainText('1');

  // Windowed still: a sort is a read, not a reason to mount sixty-one works.
  const mounted = await rows.count();
  expect(mounted, `an ordered corpus mounted ${mounted} rows`).toBeLessThan(40);
  expect(await bareNumbers(page), 'no number stands on its own').toEqual([]);
  await auditPage(page, 'the corpus ordered by accepted evidence');
  await page.screenshot({ path: info.outputPath('corpus-ordered.png'), fullPage: false });

  // The other way round is the half a page that never asked the daemon could not answer:
  // the work with evidence is not last on screen, it is off the window entirely.
  await readBy('Accepted', 'evidence', false);
  await expect(
    page.getByRole('status').filter({ hasText: 'Least accepted evidence first.' }),
  ).toBeVisible();
  await expect(accepted).toHaveAttribute('aria-sort', 'ascending');
  await expect(withEvidence).toHaveCount(0);
  await expect(rows.first().locator('.rh-web-corpus__cell').nth(3)).toContainText('0');

  // And the corpus's own order is one act away either way, so a sort is never something a
  // researcher has to reload the page to undo.
  await readBy('Accepted', 'evidence', null);
  await expect(count).toHaveText(`${corpus.works} works.`);
  await expect(accepted).toHaveAttribute('aria-sort', 'none');
  await expect(rows.first().getByRole('link', { name: 'W0001' })).toBeVisible();

  // The order outlives the visit: it is remembered per project, so the corpus opens the
  // way it was left rather than in the daemon's order followed by a re-sort.
  await readBy('Accepted', 'evidence', true);
  await expect(accepted).toHaveAttribute('aria-sort', 'descending');
  await page.reload();
  await expect(
    page.getByRole('status').filter({ hasText: 'Most accepted evidence first.' }),
  ).toBeVisible();
  await expect(
    page.locator('.rh-web-corpus__column').filter({ hasText: 'Accepted' }).first(),
  ).toHaveAttribute('aria-sort', 'descending');
  // The control the width offers reads the order it left, in the same words the count does.
  if (!wide) await expect(select).toHaveValue('evidence:desc');
  expect(errors).toEqual([]);
});
