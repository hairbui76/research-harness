/**
 * What the cockpit does when there is too much of something, or none of the daemon.
 *
 * Three properties, none of which a unit test can settle on its own. A corpus of a thousand
 * works has to render in a real browser against the real backend to say anything about how
 * long it takes and how much of it is in the DOM. A daemon that stops answering has to stop
 * answering a real client, which is what `page.route(...).abort()` does while the backend
 * stays up. And a container query is a layout decision the browser makes: whether it fires
 * can only be seen by making a pane narrow at a viewport that is not.
 */
import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

/** How many works the corpus is seeded with. Far past the few hundred a real project has. */
const WORKS = 1000;

/**
 * The corpus page is the one screen whose length nothing bounds, and rendering it is the
 * measurement, so the budget is generous but real: a thousand works, a four-second capability
 * read behind them, and a cold Chromium.
 */
const RENDER_BUDGET_MS = 30_000;

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** Redeem a bootstrap nonce so this browser holds the application token. */
async function signIn(page: import('@playwright/test').Page, request: import('@playwright/test').APIRequestContext) {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  // Generous, because the registry this lists may hold a thousand-work workspace by now and
  // the host opens each project to say whether it is available.
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible({
    timeout: 180_000,
  });
}

/** The corpus page's own find. The rail has a search box too, so this one is named. */
function findAWork(page: import('@playwright/test').Page) {
  return page.getByRole('searchbox', { name: /Find a work/ });
}

/**
 * A project whose corpus is a thousand works.
 *
 * The server builds it once and hands the same project to both viewport runs: a thousand
 * works is a minute of durable writes, this screen only reads them, and building one per
 * viewport would double the cost of the run to prove nothing.
 */
async function corpusOf(
  request: import('@playwright/test').APIRequestContext,
  works: number,
) {
  const seeded = await request.post(`/__test__/large-corpus?works=${works}`, {
    timeout: 900_000,
  });
  expect(seeded.ok()).toBeTruthy();
  return (await seeded.json()) as { project_id: string; works: string; corpus_url: string };
}

test('a thousand works render inside a budget, and only a window of them is in the DOM', async ({
  page,
  request,
}, info) => {
  // Seeding a thousand works durably is minutes of fsync, and the render measurement sits
  // behind it.
  test.setTimeout(900_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await signIn(page, request);
  const corpus = await corpusOf(request, WORKS);
  expect(corpus.works).toBe(String(WORKS));

  const started = Date.now();
  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();
  const count = page.getByRole('status').filter({ hasText: `${WORKS} works.` });
  await expect(count).toBeVisible({ timeout: RENDER_BUDGET_MS });
  const list = page.getByRole('list', { name: 'Works in the corpus' });
  await expect(list.getByRole('listitem').first()).toBeVisible({ timeout: RENDER_BUDGET_MS });
  const elapsed = Date.now() - started;

  const mounted = await list.getByRole('listitem').count();
  console.log(
    `[resilience/${info.project.name}] ${WORKS} works: first card visible in ${elapsed}ms, ` +
      `${mounted} of ${WORKS} cards in the DOM`,
  );
  expect(elapsed, `a corpus of ${WORKS} took ${elapsed}ms to draw`).toBeLessThan(
    RENDER_BUDGET_MS,
  );
  // Bounded, and bounded far below the corpus. The exact number is the window plus its
  // overscan and is not the contract; that there is a bound is.
  expect(mounted).toBeGreaterThan(0);
  expect(mounted).toBeLessThan(40);

  // The page is one scroller and it does not run off the side, at this width or the other.
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, 'the corpus page overflows sideways').toBe(true);

  // The list is a named region, it takes a tab stop, and the far end of the corpus is
  // reachable from the keyboard rather than only from a scrollbar.
  await list.focus();
  await page.keyboard.press('End');
  await expect(page.getByText(`Synthetic corpus study ${String(WORKS).padStart(4, '0')}`)).toBeVisible();
  expect(await list.getByRole('listitem').count()).toBeLessThan(40);
  await page.keyboard.press('Home');

  // And a work in the middle of it is reachable without scrolling at all.
  await findAWork(page).fill('study 0500');
  await expect(page.getByRole('link', { name: 'W0500' })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: `Showing 1 of ${WORKS} works.` })).toBeVisible();
  await findAWork(page).fill('');

  expect(await axeViolations(page)).toEqual([]);

  await page.screenshot({ path: info.outputPath('corpus-thousand-works.png'), fullPage: false });
  expect(errors).toEqual([]);
});

test('a daemon that stops answering becomes one polite notice, and comes back', async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  await signIn(page, request);
  // A small project on purpose: losing the daemon has nothing to do with how much a project
  // holds, and reading a thousand works back is time this assertion should not be spending.
  const corpus = await corpusOf(request, 5);
  const workspace = `/projects/${corpus.project_id}`;

  await page.goto(`${workspace}/claims`);
  await expect(page.getByRole('heading', { level: 1, name: 'Claims' })).toBeVisible({
    timeout: 120_000,
  });

  // Take the daemon away from this client only. The backend stays up — the control plane
  // still answers — so what is being tested is a workspace daemon that has gone quiet, not
  // a browser that has gone offline.
  const workspaceApi = '**/api/projects/*/capabilities/**';
  const workspaceOverview = '**/api/projects/*/overview';
  await page.route(workspaceApi, (route) => route.abort('connectionrefused'));
  await page.route(workspaceOverview, (route) => route.abort('connectionrefused'));

  await page.reload();

  const notice = page.getByRole('status').filter({ hasText: 'Research Harness is not answering' });
  // Generous: the reload re-runs host detection, and listing a registry that holds a
  // thousand-work workspace is seconds of work before this window is a window at all.
  await expect(notice).toBeVisible({ timeout: 120_000 });
  // Polite: a status, not an alert, and not a dialog over the page.
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(notice).toContainText('Your draft is safe.');
  await expect(notice).toContainText('research app');

  // One condition, one notice, one way to ask again. The capture used to show two, because
  // the open page put its own "Try again: Waiting for the daemon" under this one.
  const retries = await page.getByRole('button', { name: /again/i }).allInnerTexts();
  expect(retries, `the page offered ${retries.length} ways to ask again`).toEqual([
    'Ask the daemon again',
  ]);

  // The page frame is still mounted underneath it: the heading, its description, and the
  // navigation that gets a researcher to another screen.
  await expect(page.getByRole('heading', { level: 1, name: 'Claims' })).toBeVisible();
  await expect(page.getByRole('main')).toBeVisible();
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, 'the offline notice pushes the page sideways').toBe(true);

  await page.screenshot({ path: info.outputPath('daemon-offline.png'), fullPage: false });

  expect(await axeViolations(page)).toEqual([]);

  // Give the daemon back and ask once. The notice clears with no reload.
  await page.unroute(workspaceApi);
  await page.unroute(workspaceOverview);
  const answered = page.waitForResponse(
    (response) => response.url().endsWith('/overview'),
    { timeout: 120_000 },
  );
  await page.getByRole('button', { name: 'Ask the daemon again' }).click();
  expect((await answered).ok()).toBeTruthy();
  await expect(notice).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole('heading', { level: 1, name: 'Claims' })).toBeVisible();
});

test('a narrow pane gets the narrow layout at a wide viewport', async ({ page, request }, info) => {
  test.setTimeout(300_000);
  await signIn(page, request);
  // The container query is about the pane's width, not about how much is in it.
  const corpus = await corpusOf(request, 5);

  await page.goto(corpus.corpus_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();
  // The toolbar is only itself once the corpus has arrived, so wait for what is in it.
  await expect(findAWork(page)).toBeVisible({ timeout: RENDER_BUDGET_MS });

  const header = page.locator('.rh-full-page__header');
  const heading = page.locator('.rh-full-page__heading');
  const toolbar = page.locator('.rh-full-page__toolbar');
  const direction = () => header.evaluate((node) => getComputedStyle(node).flexDirection);

  // Wide pane: the title and the find share a line.
  expect(await direction(), 'the wide page header should be a row').toBe('row');
  const wideToolbar = (await toolbar.boundingBox())!;
  const wideHeading = (await heading.boundingBox())!;
  expect(
    wideToolbar.y,
    'the toolbar should share the title’s line while the pane is wide',
  ).toBeLessThan(wideHeading.y + wideHeading.height);

  // Narrow the *pane*, not the window. The viewport is untouched, so a viewport query
  // would still call this wide; the container query sees the 480px the page actually has.
  await page.addStyleTag({
    content: '.rh-app-shell__main { max-inline-size: 480px; }',
  });
  await expect.poll(direction, { timeout: 10_000 }).toBe('column');

  // And the visible consequence: the find takes its own row under the title.
  const narrowToolbar = (await toolbar.boundingBox())!;
  const narrowHeading = (await heading.boundingBox())!;
  expect(narrowToolbar.y).toBeGreaterThanOrEqual(narrowHeading.y + narrowHeading.height);

  const paneWidth = await page.locator('.rh-full-page').evaluate((node) => node.clientWidth);
  const viewport = page.viewportSize()!;
  expect(paneWidth, 'the pane should be narrower than the window it is in').toBeLessThan(
    viewport.width,
  );
  console.log(
    `[resilience/${info.project.name}] pane ${paneWidth}px inside a ${viewport.width}px window: ` +
      'the page toolbar took its own row',
  );

  await page.screenshot({ path: info.outputPath('narrow-pane.png'), fullPage: false });
});

/**
 * The other two query containers, at a window that is not narrow.
 *
 * `rh-page` is the one the test above measures; the cockpit declares two more, and neither
 * of them answers the window either. `rh-centre` is the conversation's middle column, which
 * the rail and an open inspector leave at about 415px inside a 1024px window, and
 * `rh-inspector` is the pane itself, which is 22rem beside a page and 85vw as a drawer.
 * Whether a container query fires is a decision the browser makes about one element's own
 * width, so each half below reads the rule's visible effect at 1024 and then changes only
 * that element's width.
 *
 * The effect is measured rather than the `display` property: a flex item's `display` is
 * blockified, so `inline-flex` and `flex` both compute to `flex` on the model cluster and
 * reading it would assert nothing. What the rule actually does is give the cluster the
 * composer's whole width, and that is what is measured.
 *
 * The conversation is seeded with a turn because the composer only offers its model cluster
 * once a session has something to send, and that cluster is what the `rh-centre` rule moves.
 */
test('the conversation panes answer their own width, not the window’s', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/session-with-turn', { timeout: 60_000 });
  expect(seeded.ok()).toBeTruthy();
  const conversation = await seeded.json();

  await page.setViewportSize({ width: 1024, height: 900 });
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(conversation.conversation_url);
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();

  // -- rh-centre: below 30rem the model cluster takes the composer's width ---
  await expect(page.locator('.rh-web-composer__model')).toBeVisible();
  const centre = () =>
    page.evaluate(() => ({
      pane: document.querySelector('.rh-conversation-workspace__centre')?.clientWidth ?? 0,
      cluster:
        document.querySelector('.rh-web-composer__model')?.getBoundingClientRect().width ?? 0,
      toolbar: document.querySelector('.rh-composer__toolbar')?.getBoundingClientRect().width ?? 0,
      window: window.innerWidth,
    }));

  const packed = await centre();
  expect(packed.window, 'the window is not narrow').toBe(1024);
  expect(packed.pane, 'the rail and the inspector leave the centre inside 30rem').toBeLessThan(
    480,
  );
  expect(
    Math.abs(packed.cluster - packed.toolbar),
    'a narrow centre gives the model cluster the composer’s whole width',
  ).toBeLessThan(1);

  // -- rh-inspector: below 20rem the panel gives its padding back -----------
  const toggle = page.getByRole('button', { name: /^(Show|Hide) the research inspector$/ });
  if ((await toggle.innerText()).startsWith('Show')) await toggle.click();
  await expect(page.getByRole('region', { name: 'Research inspector' })).toBeVisible();
  const panel = page.locator('.rh-research-inspector__panel').first();
  const padding = () => panel.evaluate((node) => getComputedStyle(node).paddingTop);
  const roomy = await padding();

  // The inspector is the container, so narrowing it is narrowing the query's own subject.
  await page.addStyleTag({ content: '.rh-research-inspector { max-inline-size: 300px; }' });
  await expect.poll(padding, { timeout: 10_000 }).not.toBe(roomy);
  expect(
    Number.parseFloat(await padding()),
    'a narrow inspector gives the panel’s padding back to its content',
  ).toBeLessThan(Number.parseFloat(roomy));

  // And the centre lets go of its rule when the pane grows, at the same 1024 window.
  await page.addStyleTag({ content: '.rh-app-shell__main { min-inline-size: 700px; }' });
  await expect
    .poll(async () => {
      const grown = await centre();
      return grown.pane > 480 && grown.toolbar - grown.cluster > 100;
    }, { timeout: 10_000 })
    .toBe(true);

  const grown = await centre();
  console.log(
    `[resilience/${info.project.name}] centre ${packed.pane}px then ${grown.pane}px inside the ` +
      'same 1024px window: the composer took the narrow rule and then let it go',
  );

  await page.screenshot({ path: info.outputPath('narrow-conversation.png'), fullPage: false });
  expect(errors).toEqual([]);
});
