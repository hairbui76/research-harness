import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

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
 * - **And so is the meaning of a word that is not a state.** The tier, the evidence type,
 *   the strength and the origin stand as values rather than badges, and each answers the
 *   same gesture: a tab stop, a sentence named by it, the sentence printed underneath.
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

  expect(await axeViolations(page), 'the review inbox').toEqual([]);
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
  // The staging handle the daemon minted for this proposal. It addresses the card and the
  // URL; it is not a word a researcher reads (2E).
  expect(review, 'the review screen prints a `cand_` identifier').not.toMatch(/cand_[0-9a-f]/);
  // An open dictionary is read out as a line; braces belong in a file, not on a page.
  expect(review).not.toMatch(/[{}]/);

  expect(await axeViolations(page), 'the evidence review screen').toEqual([]);
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

/** Every word on a screen that offers its meaning, whether it is drawn as a badge or not. */
const DESCRIBED = '.rh-described-term__word, .rh-badge[tabindex="0"]';

/** The sentence a described word is currently printing for the eye. */
const HINT = '.rh-described-term__hint, .rh-authority-badge__hint';

/**
 * Walk the page with Tab, and read every meaning it offers on the way.
 *
 * The walk is the assertion: a sentence that only a mouse can open, or that lives in a
 * `title`, is exactly what this screen is not allowed to have. Each described word must
 * take a tab stop, name its own sentence for a screen reader, and print that same sentence
 * under itself while it holds focus.
 */
async function tabThroughMeanings(
  page: import('@playwright/test').Page,
): Promise<Map<string, string>> {
  // The page reads itself before it has any of these, so wait for the first one rather
  // than walking an empty screen and concluding it says nothing.
  await expect(page.locator(DESCRIBED).first()).toBeVisible({ timeout: 15_000 });
  const total = await page.locator(DESCRIBED).count();
  const found = new Map<string, string>();

  await page.locator('h1').first().click();
  for (let step = 0; step < 200 && found.size < total; step += 1) {
    await page.keyboard.press('Tab');
    const focused = page.locator(':focus');
    if ((await focused.count()) === 0) continue;
    const describes = await focused.evaluate(
      (element) =>
        element.classList.contains('rh-described-term__word') ||
        (element.classList.contains('rh-badge') && element.hasAttribute('aria-describedby')),
    );
    if (!describes) continue;

    const word = ((await focused.textContent()) ?? '').trim();
    expect(await focused.getAttribute('title'), `"${word}" hides its meaning in a title`).toBeNull();
    const describedBy = await focused.getAttribute('aria-describedby');
    expect(describedBy, `"${word}" names no sentence`).toBeTruthy();
    const sentence = ((await page.locator(`#${describedBy}`).textContent()) ?? '').trim();
    expect(sentence.length, `"${word}" is named by an empty sentence`).toBeGreaterThan(0);

    // The visible half is the same sentence, and it is there because this word has focus.
    await expect(page.locator(HINT).first()).toHaveText(sentence);
    found.set(word, sentence);
  }
  return found;
}

test('every word the review screen prints as a value defines itself to the keyboard', async ({
  page,
  request,
}, info) => {
  await seedQueue(page, request);

  // The queue first: the tier is the phrase a first-timer meets before anything else, and
  // it is not a badge, so it has to answer the same gesture the badges beside it do.
  const inbox = await tabThroughMeanings(page);
  expect([...inbox.keys()]).toContain('Tier 2 — deep review');
  expect(inbox.get('Tier 2 — deep review')).toMatch(/Interpretation/);
  expect(inbox.get('High-risk scientific claims')).toMatch(/carries a number/);

  // Captured with the sentence open, because what is being reviewed is the sentence in
  // place: the row keeps its shape and the meaning sits under the word it explains.
  await page.getByText('Tier 2 — deep review').first().click();
  await expect(page.locator(HINT).first()).toContainText('Interpretation');
  await page.screenshot({ path: info.outputPath('vocabulary-inbox-tier.png'), fullPage: true });

  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible({ timeout: 15_000 });

  const review = await tabThroughMeanings(page);
  // The four the critique named as undefined, and the states this screen is about.
  expect(review.get('Experimental result')).toMatch(/kind of statement/);
  expect(review.get('Direct')).toMatch(/How directly the source supports/);
  expect(review.get('Source observed')).toMatch(/measured or reported/);
  expect(review.get('Metric result')).toMatch(/measured result/);
  expect(review.get('Valid')).toMatch(/still replays/);
  expect(review.get('Supported')).toMatch(/independent reader/);
  expect(review.get('Candidate')).toMatch(/Proposed and awaiting review/);

  // Nowhere on the screen is a meaning hidden where a keyboard or a touch cannot reach it.
  expect(
    await page.locator('.rh-described-term__word[title], .rh-badge[title]').count(),
  ).toBe(0);

  /*
   * Describing one term must not move the terms beside it.
   *
   * The five facts on the evidence card are a row of tab stops. The sentence used to open
   * inside the fact that owns it, which widened that fact and re-wrapped the row: focusing
   * STRENGTH sent ORIGIN and FIELD — the next two tab stops — somewhere else, so the
   * keyboard walk aimed at a moving target and the eye lost its place. The sentence now
   * spans its own row beneath the terms, and the terms hold position.
   */
  const factWords = page.locator('.rh-evidence-card__facts .rh-described-term__word');
  const before = await factWords.evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      return { text: (node.textContent ?? '').trim(), x: Math.round(box.x), y: Math.round(box.y) };
    }),
  );
  expect(before.length, 'the review card must show described facts').toBeGreaterThan(2);

  await page.getByText('Direct', { exact: true }).first().click();
  await expect(page.locator(HINT).first()).toContainText('How directly the source supports');

  const after = await factWords.evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      return { text: (node.textContent ?? '').trim(), x: Math.round(box.x), y: Math.round(box.y) };
    }),
  );
  expect(
    after.filter((term) => term.text !== 'Direct'),
    'describing one term moved the terms beside it',
  ).toEqual(before.filter((term) => term.text !== 'Direct'));

  await page.screenshot({ path: info.outputPath('vocabulary-review-described.png'), fullPage: true });
});
