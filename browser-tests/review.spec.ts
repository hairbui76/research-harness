import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

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

  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits, 'The review inbox must not overflow horizontally').toBeTruthy();
  await page.screenshot({ path: info.outputPath('review-inbox.png'), fullPage: true });

  // The batch previews before it writes, and says what it would leave behind.
  await page.getByRole('button', { name: /Accept the routine candidates/ }).click();
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

  // The palette reaches the rail's destinations without the rail being on screen.
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog', { name: 'Go to, or do' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('command-palette.png'), fullPage: true });
  await page.getByRole('combobox', { name: 'Search screens and actions' }).fill('corpus');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Corpus', level: 1 })).toBeVisible();

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
  const overlaps = async (selector: string): Promise<boolean> =>
    page.evaluate((css) => {
      const notice = document.querySelector('.rh-toast');
      const other = document.querySelector(css);
      if (notice === null || other === null) return false;
      const a = notice.getBoundingClientRect();
      const b = other.getBoundingClientRect();
      return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    }, selector);
  expect(await overlaps('.rh-full-page__header'), 'the toast covers the page header').toBe(
    false,
  );
  expect(
    await overlaps('.rh-review-decision-bar'),
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

  // `?` teaches the keys rather than leaving them to be guessed.
  await page.keyboard.press('?');
  const help = page.getByRole('dialog', { name: 'Keyboard shortcuts' });
  await expect(help).toBeVisible();
  await expect(help).toContainText('Request more evidence');
  await page.screenshot({ path: info.outputPath('shortcut-help.png'), fullPage: true });
});
