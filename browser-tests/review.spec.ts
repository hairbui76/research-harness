import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

/**
 * The review loop in a real browser, against the real daemon.
 *
 * `/__test__/review-queue` builds a project and stages the Gate P11 candidates through the
 * daemon's own services, so everything below is driven against real staging, a real queue
 * and real capability calls — the cockpit's fakes prove the wiring, this proves the loop.
 * The Accept ceremony is deliberately not exercised here: Defer takes a typed note and is
 * the safe way to prove that deciding moves a researcher on.
 */

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** A project whose review queue already holds the three staged candidates. */
async function seedQueue(page: import('@playwright/test').Page, request: import('@playwright/test').APIRequestContext) {
  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/review-queue', { timeout: 60_000 });
  expect(seeded.ok()).toBeTruthy();
  const queue = await seeded.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(queue.review_url);
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  return queue;
}

test('the queue can be searched, batched and reached from the keyboard', async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await seedQueue(page, request);

  // What the daemon staged, in the daemon's own groups and counts.
  await expect(page.getByText('3 waiting.')).toBeVisible();
  await expect(page.getByText('High-risk scientific claims (1)')).toBeVisible();
  await expect(page.getByText('Ambiguous extractions (1)')).toBeVisible();
  await expect(page.getByText('Routine verified candidates (1)')).toBeVisible();
  await expect(page.getByRole('link', { name: /Metric result · W0001/ })).toBeVisible();

  expect(await axeViolations(page), 'the review inbox').toEqual([]);
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits, 'The review inbox must not overflow horizontally').toBeTruthy();
  await page.screenshot({ path: info.outputPath('review-inbox.png'), fullPage: true });

  // The batch acts on the queue, so its control sits in the toolbar beside the filters
  // rather than after every card, and nothing about it is on the page until it is pressed.
  const batch = page.getByRole('button', { name: /Accept the routine candidates/ });
  await expect(batch).toBeVisible();
  expect(
    await batch.evaluate((node) => node.closest('.rh-full-page__toolbar') !== null),
    'the batch control belongs in the toolbar',
  ).toBe(true);

  // A candidate the daemon filed as routine can be decided on its own row. Accepting still
  // restates what it writes and waits for a second press.
  const routine = page.getByRole('group', { name: 'Decide Dataset · W0001' });
  await expect(routine).toBeVisible();
  await routine.getByRole('button', { name: 'Accept' }).click();
  await expect(
    page.getByText(/Accept as evidence for Dataset of W0001/),
  ).toBeVisible();
  await expect(page.getByText(/No review action takes an acceptance back/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('review-row-decision.png'), fullPage: true });
  await page.getByRole('button', { name: 'Cancel' }).click();

  // The batch previews before it writes, and says what it would leave behind.
  await batch.click();
  await expect(page.getByText('1 routine candidate meets the batch conditions.')).toBeVisible();
  const meets = page.getByRole('list', { name: 'Candidates that meet the batch conditions' });
  await expect(meets.getByRole('listitem')).toHaveText(['Dataset · W0001']);
  const left = page.getByRole('list', { name: 'Candidates the batch would leave in the queue' });
  await expect(left.getByText(/numeric evidence is never low risk/)).toBeVisible();
  await expect(left.getByText(/verdict is partially supported, not supported/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accept 1 candidate' })).toBeEnabled();
  await page.screenshot({ path: info.outputPath('review-batch-preview.png'), fullPage: true });
  await page.getByRole('button', { name: 'Cancel' }).click();

  // A filter narrows the queue, and one that matches nothing says so and offers a way out.
  const filter = page.getByRole('textbox', { name: /Filter by field/ });
  await filter.fill('transformer');
  await expect(page.getByText('Showing 1 of 3 waiting.')).toBeVisible();
  await expect(page.getByRole('link', { name: /Method summary · W0001/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /Metric result · W0001/ })).toHaveCount(0);

  await filter.fill('no span says this');
  await expect(page.getByText(/No candidate matches these filters/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('review-no-matches.png'), fullPage: true });
  await page.getByRole('button', { name: 'Clear the filters' }).click();
  await expect(page.getByText('3 waiting.')).toBeVisible();

  // The palette reaches the rail's destinations without the rail being on screen, says
  // which two keys get there without it, and shows that this screen has actions at all
  // before anything is typed (wave 5J).
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog', { name: 'Go to, or do' })).toBeVisible();
  await expect(page.getByRole('option', { name: /Corpus/ }).locator('kbd')).toHaveText(['g', 'c']);
  const actions = page.getByRole('group', { name: 'Actions' });
  await expect(actions).toBeVisible();
  await expect(actions.getByRole('option', { name: /Keyboard shortcuts/ })).toBeVisible();
  // Eleven destinations fill the pane, so what is in the list is also said above it.
  await expect(page.getByText(/screens to go to, and \d+ actions on this screen\./)).toBeVisible();

  /*
   * The two headings are not peers, and have to look it.
   *
   * "Go to" and "Actions" divide the palette in half; "Waiting", "The record" and
   * "Outputs" are the rail's own runs inside the first half. Both were set in the same
   * label role one ink step apart, so "Go to" read as a sibling of the runs rather than
   * as the half that contains them. The section heading takes the `ui` role in primary
   * ink; the run headings keep the label role in muted ink.
   */
  const hierarchy = await page.evaluate(() => {
    const read = (selector: string) => {
      const node = document.querySelector(selector);
      if (node === null) throw new Error(`no ${selector} in the palette`);
      const style = getComputedStyle(node);
      return {
        size: Number.parseFloat(style.fontSize),
        weight: Number.parseInt(style.fontWeight, 10),
        colour: style.color,
        transform: style.textTransform,
      };
    };
    return {
      section: read('.rh-web-palette__section-heading'),
      group: read('.rh-web-palette__heading'),
    };
  });
  expect(
    hierarchy.section.size,
    'the palette section heading must not be the size of a run heading',
  ).toBeGreaterThan(hierarchy.group.size);
  expect(
    hierarchy.section.colour,
    'the palette section heading must not take the run headings’ ink',
  ).not.toEqual(hierarchy.group.colour);
  // Heading weight, and sentence case: the label role's uppercase belongs to a `<dt>` or a
  // column name, and a heading that shouted would trade one flat hierarchy for another.
  expect(hierarchy.section.weight).toBe(600);
  expect(hierarchy.section.transform).toEqual('none');

  await page.screenshot({ path: info.outputPath('command-palette.png'), fullPage: true });
  await page.getByRole('combobox', { name: 'Search screens and actions' }).fill('corpus');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Corpus', level: 1 })).toBeVisible();

  // And the chord itself: `g` opens it, says so, and the letter after it goes to the screen
  // whose name that letter is in. The heading is clicked first only to put the caret
  // somewhere that is not a text box, which is where a researcher's hands would leave it.
  await page.getByRole('heading', { name: 'Corpus', level: 1 }).click();
  await page.keyboard.press('g');
  const waiting = page.locator('.rh-web-chord');
  await expect(waiting).toHaveText(/Go to a screen/);
  await page.screenshot({ path: info.outputPath('chord-waiting.png'), fullPage: true });
  await page.keyboard.press('r');
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();
  await expect(waiting).toHaveCount(0);

  expect(errors).toEqual([]);
});

/**
 * Whether the notification on screen covers the box `selector` names.
 *
 * A toast is chrome and lands on chrome: never on what a researcher is reading, and never on
 * what they are reaching for. Both review tests use this while a toast is up.
 *
 * A missing element is a fault rather than a pass: an assertion that quietly holds because
 * the thing it protects had unmounted would have missed the defect this exists for.
 */
async function toastCovers(
  page: import('@playwright/test').Page,
  selector: string,
): Promise<boolean> {
  return page.evaluate((css) => {
    const notice = document.querySelector('.rh-toast');
    if (notice === null) throw new Error('no toast is on screen');
    const other = document.querySelector(css);
    if (other === null) throw new Error(`nothing on the page matches ${css}`);
    const a = notice.getBoundingClientRect();
    const b = other.getBoundingClientRect();
    return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  }, selector);
}

/**
 * A deep review is refused from the queue, and the keyboard is handed on.
 *
 * Tier 2 is the queue's deepest filing, and the tier is what withholds Accept from the row:
 * an acceptance writes authority into the project, and Product 26 puts the source beside
 * that decision. Refusing one writes no evidence, so it happens where the row is — with the
 * sentence the daemon records the refusal with, typed on the row itself. The candidate then
 * leaves the queue, taking the control that had the focus with it, and the focus lands on
 * the next candidate in the queue's own order rather than at the top of the document.
 */
test('a deep review is refused from the queue, and the focus lands on the next row', async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await seedQueue(page, request);

  const row = page.getByRole('group', { name: 'Decide Metric result · W0001' });
  await expect(row).toBeVisible();
  await expect(row.getByRole('button', { name: 'Defer' })).toBeVisible();
  await expect(row.getByRole('button', { name: 'Accept' })).toHaveCount(0);
  // The way to the screen where its acceptance is taken: the same candidate the row names.
  const candidate = await page.getByRole('link', { name: /Metric result · W0001/ }).getAttribute('href');
  await expect(row.getByRole('link', { name: 'Open to decide' })).toHaveAttribute(
    'href',
    String(candidate),
  );
  await page.screenshot({ path: info.outputPath('review-row-deep.png'), fullPage: true });

  // The sentence is asked for on the row, in a field rather than in a dialog over the queue.
  await row.getByRole('button', { name: 'Reject' }).click();
  const form = page.getByRole('form', { name: 'Reject Metric result · W0001' });
  await expect(form).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await form
    .getByLabel('Why this candidate is refused')
    .fill('the cell is the baseline, not this model');
  await page.screenshot({ path: info.outputPath('review-row-reject.png'), fullPage: true });
  await form.getByRole('button', { name: 'Reject', exact: true }).click();

  /*
   * The notice about the decision does not cover what the decision changed.
   *
   * The queue's count is the sentence a researcher reads to see the refusal took — and at
   * 768px, where the toast takes the width of the screen, it landed exactly there: the strip
   * that said "Candidate rejected." sat on top of "2 waiting.". The count belongs to the
   * toolbar that filters it, so it is in the page header now, which is the region the
   * viewport already measures and clears. Asserted at both widths, while the toast is up.
   */
  const count = page.locator('.rh-web-inbox-count');
  await expect(count).toHaveText('2 waiting.');
  const notice = page.getByRole('region', { name: 'Notifications' }).locator('.rh-toast').first();
  await expect(notice).toBeVisible();
  expect(await toastCovers(page, '.rh-full-page__header'), 'the toast covers the page header').toBe(
    false,
  );
  expect(
    await toastCovers(page, '.rh-web-inbox-count'),
    'the toast covers the queue’s count',
  ).toBe(false);

  await expect(page.getByText('2 waiting.')).toBeVisible();
  await expect(page.getByRole('link', { name: /Metric result · W0001/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Method summary · W0001/ })).toBeFocused();
  expect(await axeViolations(page), 'the queue with every row decidable').toEqual([]);
  await page.screenshot({ path: info.outputPath('review-row-rejected.png'), fullPage: true });

  expect(errors).toEqual([]);
});

/**
 * Put every scroller back where a researcher starts reading.
 *
 * Below 1100px the two review panes stack, and the page workspace — not the document — is
 * what scrolls. A decision is taken at the bottom of that stack, so a capture made straight
 * afterwards prints a screen nobody ever sees: the proposal clipped under the sticky header,
 * the source pane above the fold, and blank canvas below. The source is reachable the whole
 * time; the capture simply has to start from the top, and the assertion below is what says
 * so rather than the screenshot.
 */
async function toTop(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (const node of Array.from(document.querySelectorAll('*'))) {
      if (node instanceof HTMLElement && node.scrollTop > 0) node.scrollTop = 0;
    }
  });
}

test('deciding a candidate offers the next one in the queue’s own order', async ({ page, request }, info) => {
  await seedQueue(page, request);

  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Next: Method summary · W0001' })).toBeVisible();

  await page.getByRole('button', { name: 'Defer', exact: true }).click();
  await page.getByLabel('Why this is being put aside').fill('waiting for the appendix');
  await page.getByRole('button', { name: 'Defer', exact: true }).nth(1).click();
  await expect(page.getByText('Candidate deferred.').first()).toBeVisible();

  /*
   * A notification lands on chrome, never on what is being read or reached for.
   *
   * Wave one moved the viewport off the decision controls; at 768px the corner it moved to
   * is the page's own header, and the capture showed the toast over "Nothing here is
   * accepted state." Both are asserted here, at both widths, while the toast is up.
   */
  const toast = page.getByRole('region', { name: 'Notifications' }).locator('.rh-toast').first();
  await expect(toast).toBeVisible();
  expect(await toastCovers(page, '.rh-full-page__header'), 'the toast covers the page header').toBe(
    false,
  );
  expect(
    await toastCovers(page, '.rh-review-decision-bar'),
    'the toast covers the decision controls',
  ).toBe(false);

  await toTop(page);
  await page.screenshot({ path: info.outputPath('review-decided.png'), fullPage: true });

  // Source beside decision holds at both widths: the page the span was read off, the
  // section it sits in, and the exact text are all reachable without leaving the screen.
  const rendered = page.getByRole('img', { name: /^page 4 of / });
  await rendered.scrollIntoViewIfNeeded();
  await expect(rendered).toBeVisible();
  await expect(page.getByText('4 Results', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Source text' })).toBeVisible();

  await page.getByRole('link', { name: 'Next: Method summary · W0001' }).click();
  await expect(
    page.getByRole('heading', { name: 'Method summary · W0001', level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Previous: Metric result · W0001' })).toBeVisible();

  // `?` teaches the keys rather than leaving them to be guessed — the screen's own single
  // keys, and the chords that go somewhere, each under their own heading (wave 5J).
  await page.keyboard.press('?');
  const help = page.getByRole('dialog', { name: 'Keyboard shortcuts' });
  await expect(help).toBeVisible();
  await expect(help).toContainText('Request more evidence');
  await expect(help.getByRole('heading', { name: 'Go to a screen' })).toBeVisible();
  await expect(
    help.locator('.rh-web-shortcuts__row', { hasText: 'Review inbox' }).locator('kbd'),
  ).toHaveText(['g', 'r']);
  await page.screenshot({ path: info.outputPath('shortcut-help.png'), fullPage: true });
});

/**
 * The act this screen exists for is on screen at the height it is worked at.
 *
 * Proposal, number, verification and conflict all belong above the decision — they are what
 * the decision is made out of — and that order used to put the six actions below the fold on
 * a 1024px window. The panel is pinned to the foot of its own scroller now, so the source
 * stays beside the decision instead of being replaced by it.
 */
test('the decision is in reach without scrolling for it', async ({ page, request }, info) => {
  await seedQueue(page, request);
  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible();

  const pinned = await page.evaluate(() => {
    const panel = document.querySelector('.rh-web-decide');
    return panel === null ? null : getComputedStyle(panel).position;
  });
  expect(pinned, 'the decision panel must be pinned, not merely last').toBe('sticky');

  const box = async (): Promise<{ top: number; bottom: number; height: number; view: number }> =>
    page.evaluate(() => {
      const bar = document.querySelector('.rh-review-decision-bar');
      const rect = (bar as HTMLElement).getBoundingClientRect();
      return {
        top: rect.top,
        bottom: rect.bottom,
        height: rect.height,
        view: window.innerHeight,
      };
    });

  const viewport = page.viewportSize();
  if ((viewport?.width ?? 0) > 1100) {
    // Source beside decision: the pane scrolls, the decision does not leave it.
    const rect = await box();
    expect(
      rect.height > 0 && rect.top >= 0 && rect.bottom <= rect.view,
      `the decision controls were at ${rect.top}-${rect.bottom} in a ${rect.view}px window`,
    ).toBe(true);
  } else {
    // Stacked, and the workspace is the one scroller: the panel pins to the bottom of the
    // window for as long as the proposal it belongs to is on screen.
    await page.getByRole('heading', { name: 'Verification' }).scrollIntoViewIfNeeded();
    const rect = await box();
    expect(
      rect.height > 0 && rect.bottom <= rect.view + 1,
      `the decision controls were at ${rect.top}-${rect.bottom} in a ${rect.view}px window`,
    ).toBe(true);
  }

  await page.screenshot({ path: info.outputPath('review-decision-in-reach.png') });
});

/**
 * The queue a researcher comes back to.
 *
 * A review inbox is worked in sittings, and the toolbar used to forget between them: the
 * same category, verdict and search had to be said again on every arrival. They are
 * remembered per project now — and because nobody typed a remembered filter this morning,
 * and because the daemon ranks conflicts above everything, the toolbar has to say what is
 * narrowing the queue, what it is keeping off the screen, and how to stop it.
 */
test('the inbox opens on the queue the last visit left, and says what it is hiding', async ({
  page,
  request,
}, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const queue = await seedQueue(page, request);

  await expect(page.getByText('3 waiting.')).toBeVisible();
  await page.getByRole('combobox', { name: 'Category' }).selectOption('routine');
  await expect(page.getByText('Showing 1 of 3 waiting.')).toBeVisible();
  // Nothing calls a filter remembered while the researcher is the one applying it.
  await expect(page.locator('.rh-web-inbox-remembered')).toHaveCount(0);

  // Leave the queue for another destination and come back to it, which is the visit the
  // critique's power user makes every morning.
  await page.goto(`/projects/${queue.project_id}/corpus`);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();
  await page.goto(queue.review_url);
  await expect(page.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeVisible();

  // The queue is narrowed to what was left, the control agrees with it, and the toolbar
  // says whose filter it is in the words of the filter itself.
  await expect(page.getByRole('combobox', { name: 'Category' })).toHaveValue('routine');
  await expect(page.getByText('Routine verified candidates (1)')).toBeVisible();
  const remembered = page.locator('.rh-web-inbox-remembered');
  await expect(remembered).toContainText(
    'Narrowed to Routine verified candidates only, remembered from your last visit.',
  );

  // And what it is keeping off the screen, group by group: a queue that hides the group the
  // daemon ranked first behind "1 of 3" has decided for the researcher what they may see.
  await expect(page.locator('.rh-web-inbox-count')).toContainText(
    'The filters hide 1 in High-risk scientific claims and 1 in Ambiguous extractions.',
  );
  expect(await axeViolations(page), 'the inbox under a remembered filter').toEqual([]);
  await page.screenshot({ path: info.outputPath('review-remembered-filter.png'), fullPage: true });

  // The way out is in that line, and it is the whole queue that comes back.
  await remembered.getByRole('button', { name: 'Clear the filters' }).click();
  await expect(page.getByText('3 waiting.')).toBeVisible();
  await expect(page.locator('.rh-web-inbox-remembered')).toHaveCount(0);
  await expect(page.getByText('High-risk scientific claims (1)')).toBeVisible();

  // Cleared is remembered too: coming back a third time opens on the whole queue.
  await page.goto(queue.review_url);
  await expect(page.getByText('3 waiting.')).toBeVisible();
  await expect(page.locator('.rh-web-inbox-remembered')).toHaveCount(0);
  expect(errors).toEqual([]);
});
