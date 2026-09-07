/**
 * The Corpus page in a real browser, against the real daemon.
 *
 * The Overview's pattern says a research page opens with what needs a researcher and reads
 * the size of the project after it. The corpus is where that is hardest to hold: it is the
 * one screen whose length nothing bounds, its list is windowed, and the list itself is
 * genuinely comparative — files, versions, sizes and whether each one is parsed, read by
 * running an eye down shared columns. So the lead names the work and the table stays the
 * instrument, and what is asserted below is that both are true at once.
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

  // The works stay the instrument: the find narrows them and the live count follows it.
  const works = page.getByRole('region', { name: 'Every work in the corpus' });
  await expect(works.getByRole('columnheader', { name: 'Parsed' }).first()).toBeVisible();
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
