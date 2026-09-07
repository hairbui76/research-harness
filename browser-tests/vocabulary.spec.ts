import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * The cockpit speaks the researcher's language, in a real browser against the real daemon.
 *
 * `/__test__/review-queue` stages the same three candidates the review loop uses, through
 * the daemon's own services — so what is asserted below is what a researcher would read off
 * a real queue, not what a fixture was written to say. Two properties:
 *
 * - **No identifier reaches the screen.** `high_risk`, `partially_supported`,
 *   `metric_result` and `observed_subset` are the daemon's words for the queue's category,
 *   the verifier's verdict, the interrogation field and the claim scope ladder. None of
 *   them is text a person has to decode.
 * - **The meaning of a state is reachable.** Where the state is what the row or the screen
 *   is about, its one-line meaning is on the page — named by the badge, and printed under
 *   it when the badge takes focus. No `title` attribute, which is reachable by neither the
 *   keyboard nor touch.
 */

/** Identifiers the daemon uses internally and a researcher never has to read. */
const IDENTIFIERS = [
  'high_risk',
  'partially_supported',
  'metric_result',
  'method_summary',
  'observed_subset',
  'source_observed',
  'experimental_result',
];

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** A project whose review queue already holds the three staged candidates. */
async function seedQueue(
  page: import('@playwright/test').Page,
  request: import('@playwright/test').APIRequestContext,
) {
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

/** Everything a person can actually read on the page right now. */
async function visibleText(page: import('@playwright/test').Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

test('the queue and the review screen print no identifier a researcher must decode', async ({
  page,
  request,
}, info) => {
  await seedQueue(page, request);

  // The queue, in the product's words.
  await expect(page.getByText('High-risk scientific claims (1)')).toBeVisible();
  await expect(page.getByRole('link', { name: /Metric result · W0001/ })).toBeVisible();
  await expect(page.getByText('Tier 2 — deep review')).toBeVisible();
  await expect(page.getByText('the verifier reported partially supported')).toBeVisible();

  const inbox = await visibleText(page);
  for (const identifier of IDENTIFIERS) {
    expect(inbox, `the review inbox shows "${identifier}"`).not.toContain(identifier);
  }

  const inboxAxe = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(inboxAxe.violations).toEqual([]);
  await page.screenshot({ path: info.outputPath('vocabulary-inbox.png'), fullPage: true });

  // Open the candidate the queue named, and read the same words again.
  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible();

  const review = await visibleText(page);
  for (const identifier of IDENTIFIERS) {
    expect(review, `the review screen shows "${identifier}"`).not.toContain(identifier);
  }
  // An open dictionary is read out as a line; braces belong in a file, not on a page.
  expect(review).not.toMatch(/[{}]/);

  const reviewAxe = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(reviewAxe.violations).toEqual([]);
  await page.screenshot({ path: info.outputPath('vocabulary-review.png'), fullPage: true });
});

test('a state says what it means, and says it to the keyboard', async ({ page, request }) => {
  await seedQueue(page, request);

  // The row's own two states: why the queue is holding this, and what the verifier said.
  const row = page.locator('a[data-review-row]').first();
  await row.focus();
  await page.keyboard.press('Tab');

  const category = page
    .locator('.rh-badge[tabindex="0"]')
    .filter({ hasText: 'High-risk scientific claims' })
    .first();
  await expect(category).toBeFocused();

  // The badge is named by its meaning, and prints the same sentence while it has focus.
  const describedBy = await category.getAttribute('aria-describedby');
  expect(describedBy).toBeTruthy();
  await expect(page.locator(`#${describedBy}`)).toHaveText(/carries a number/);
  await expect(page.locator('.rh-authority-badge__hint')).toHaveText(/carries a number/);

  // And the review screen's own header badges do the same for the proposal's authority.
  // Opened from the keyboard, which is the whole point: the row is a link, and Enter on it
  // is how a researcher working the queue with `j` and `k` gets to the source.
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible({ timeout: 15_000 });

  const candidate = page
    .locator('.rh-badge[tabindex="0"]')
    .filter({ hasText: 'Candidate' })
    .first();
  await candidate.focus();
  await expect(page.locator('.rh-authority-badge__hint').first()).toHaveText(
    /Proposed and awaiting review/,
  );
  // Not one of these meanings hides in a `title`, which neither the keyboard nor touch
  // can reach.
  expect(await page.locator('.rh-badge[title]').count()).toBe(0);
});
