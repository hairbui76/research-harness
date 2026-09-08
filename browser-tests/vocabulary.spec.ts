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
  // Measured against the grid's own corner, not the viewport: clicking a term scrolls it
  // into view at the narrow width, and a scrolled page moves everything equally. What is
  // being asserted is the layout, so the origin is the layout's.
  const readTerms = (): Promise<{ text: string; x: number; y: number }[]> =>
    page.evaluate(() => {
      const facts = document.querySelector('.rh-evidence-card__facts');
      if (facts === null) throw new Error('the review card shows no facts grid');
      const origin = facts.getBoundingClientRect();
      return [...facts.querySelectorAll('.rh-described-term__word')].map((node) => {
        const box = node.getBoundingClientRect();
        return {
          text: (node.textContent ?? '').trim(),
          x: Math.round(box.x - origin.x),
          y: Math.round(box.y - origin.y),
        };
      });
    });

  const before = await readTerms();
  expect(before.length, 'the review card must show described facts').toBeGreaterThan(2);

  await page.getByText('Direct', { exact: true }).first().click();
  await expect(page.locator(HINT).first()).toContainText('How directly the source supports');

  const after = await readTerms();
  expect(
    after.filter((term) => term.text !== 'Direct'),
    'describing one term moved the terms beside it',
  ).toEqual(before.filter((term) => term.text !== 'Direct'));

  await page.screenshot({ path: info.outputPath('vocabulary-review-described.png'), fullPage: true });
});

/**
 * The row holds still while a pointer asks a badge what it means — all of it.
 *
 * This is wave two's defect, written as an assertion so it cannot come back. The sentence
 * used to open inside the badge's own box, which is a column: it widened that column, the
 * row re-wrapped, and the link the pointer was aiming at moved out from under it. That is
 * why the meaning was given to the keyboard alone, and why a mouse never learned what
 * `Candidate` meant. The sentence takes a line of its own beneath the row, so the row's
 * first line — the link, the two badges, the tier — keeps every box it had.
 *
 * That much was asserted here, and it was half the property. Wave six's finish review
 * measured the other half: a line of its own still *added* a line, so resting on "Tier 2 —
 * deep review" pushed the citation, the quote, the reason and `Reject / Defer / Open to
 * decide` down 46px, and the whole next queue group with them. A hint may never move what
 * a researcher is about to press. So the line is reserved, and what is measured below is
 * the row entire: its words, its decision controls, and the group beneath it.
 *
 * Measured against the row's own corner rather than the viewport, because a pointer
 * arriving at a badge can scroll the page and a scrolled page moves everything equally.
 * What is being asserted is the layout, so the origin is the layout's.
 */
test('a pointer resting on a queue badge never moves the row it is reading', async ({
  page,
  request,
}, info) => {
  await seedQueue(page, request);

  const row = page.locator('a[data-review-row]').first();
  await expect(row).toBeVisible({ timeout: 15_000 });

  /**
   * Every word on the row's own line: the link, the two badges, the tier.
   *
   * The link is the one the critique names, but the badges and the tier beside it are what
   * a pointer is aiming at next, and a sentence breaking the line where it stands would
   * send them to the row below while leaving the link exactly where it was. So the whole
   * line is measured, against the row's own corner.
   */
  const readRow = (): Promise<{ text: string; x: number; y: number; width: number }[]> =>
    page.evaluate(() => {
      const link = document.querySelector('a[data-review-row]');
      const item = link?.closest('li');
      if (link === null || item === null || item === undefined) {
        throw new Error('the queue shows no row');
      }
      const origin = item.getBoundingClientRect();
      const words = [link, ...item.querySelectorAll('.rh-badge, .rh-described-term__word')];
      return words.map((node) => {
        const box = node.getBoundingClientRect();
        return {
          text: (node.textContent ?? '').trim(),
          x: Math.round(box.x - origin.x),
          y: Math.round(box.y - origin.y),
          width: Math.round(box.width),
        };
      });
    });

  /**
   * Everything on the row a researcher can press, and the group under it.
   *
   * The row's own decisions sit below its words, and the next group below those; a line
   * inserted between the words and the citation moves all of it. The boxes are measured
   * against the row's corner for the same reason `readRow` is — a pointer arriving at a
   * badge can scroll the page — and the group's is measured against the row too, because
   * what is asserted is the distance from the row to what follows it.
   */
  const readControls = (): Promise<{ text: string; y: number; height: number }[]> =>
    page.evaluate(() => {
      const link = document.querySelector('a[data-review-row]');
      const item = link?.closest('li');
      if (item === null || item === undefined) throw new Error('the queue shows no row');
      const origin = item.getBoundingClientRect();
      const groups = [...document.querySelectorAll('h2')];
      const next = groups.find(
        (heading) => heading.getBoundingClientRect().top > origin.bottom,
      );
      const boxes = [...item.querySelectorAll('button, a')];
      return [...boxes, ...(next === undefined ? [] : [next])].map((node) => {
        const box = node.getBoundingClientRect();
        return {
          text: (node.textContent ?? '').trim(),
          y: Math.round(box.y - origin.y),
          height: Math.round(box.height),
        };
      });
    });

  const before = await readRow();
  expect(before.length, 'the queue row shows no words to measure').toBeGreaterThan(3);
  const controlsBefore = await readControls();
  // The three decisions the row offers, the link it opens with, and the heading of the
  // group under it: if this list is short, the assertion below is measuring nothing.
  expect(
    controlsBefore.map((control) => control.text),
    'the queue row offers nothing to press',
  ).toEqual(
    expect.arrayContaining(['Reject', 'Defer', 'Open to decide']),
  );

  const category = page
    .locator('.rh-badge[tabindex="0"]')
    .filter({ hasText: 'High-risk scientific claims' })
    .first();
  await category.hover();
  // The sentence waits for a pointer that stays, and then it is on the page for the eye.
  await expect(page.locator(HINT).first()).toContainText('carries a number', {
    timeout: 15_000,
  });

  expect(await readRow(), 'describing a badge moved the words beside it').toEqual(before);
  expect(
    await readControls(),
    'describing a badge moved the controls the row is decided with',
  ).toEqual(controlsBefore);
  await page.screenshot({ path: info.outputPath('vocabulary-inbox-hovered.png'), fullPage: true });

  // And the word a pointer cannot even see as a tab stop says so for itself: the tier is
  // not a badge, and it answers the same gesture. Its sentence is the longest on the row,
  // which is what made it the review's own example.
  const tier = page
    .locator('.rh-described-term__word')
    .filter({ hasText: 'Tier 2 — deep review' })
    .first();
  await tier.hover();
  await expect(page.locator(HINT).first()).toContainText('Interpretation', { timeout: 15_000 });
  expect(await readRow(), 'describing the tier moved the words beside it').toEqual(before);
  expect(
    await readControls(),
    'describing the tier moved the controls the row is decided with',
  ).toEqual(controlsBefore);
  await page.screenshot({ path: info.outputPath('vocabulary-inbox-tier-hovered.png') });

  // And the slot goes back to being empty rather than closing up under the pointer.
  await page.locator('h1').first().hover();
  await expect(page.locator(HINT)).toHaveCount(0);
  expect(await readControls(), 'the row closed up when the sentence left').toEqual(
    controlsBefore,
  );
});

/**
 * Green says accepted, and says nothing else.
 *
 * `success`, `error` and `info` are not separate hues — they resolve to the accepted,
 * contested and candidate families themselves — so a badge wearing the success tone is a
 * badge painting something in the accepted green. Four did: a verified extraction, a
 * supported claim, a valid anchor, an included work, none of which is accepted state. The
 * review screen is where three of them stood beside a `Candidate` and an accepted count.
 */
test('nothing but accepted state is painted in the accepted green', async ({ page, request }) => {
  await seedQueue(page, request);

  const green = () => page.locator('.rh-badge[data-tone="success"]');
  expect(await green().count(), 'the review inbox paints a feedback badge green').toBe(0);

  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible({ timeout: 15_000 });

  // The anchor's `Valid` and the verifier's `Supported` are on this screen, one column
  // from the candidate's authority. Neither is accepted state and neither is green.
  await expect(page.getByText('Valid', { exact: true }).first()).toBeVisible();
  expect(await green().count(), 'the review screen paints a feedback badge green').toBe(0);

  // The one badge that may be green is the one that says so.
  for (const badge of await page.locator('.rh-badge[data-status]').all()) {
    const status = await badge.getAttribute('data-status');
    expect(['accepted', 'candidate', 'qualified', 'contested', 'stale', 'private']).toContain(
      status,
    );
  }
});
