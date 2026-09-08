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
 * The source stays beside the decision at every width, and the decision cuts nothing.
 *
 * The third critique's second P1. Below the width where the two panes fit side by side the
 * screen stacks — which is right — and the source pane went above the fold while the
 * decision stayed at the bottom, so §26's "the exact source beside the proposed decision"
 * held at 1440 and lapsed at 1024. And at 1440 the pinned card was opaque to its own top
 * edge, so it cut the `UNIT percent` row of the Number panel in half and said nothing about
 * it. Both are measured here, at the two project widths and at 1024×768, which is the
 * window a laptop review is actually done in.
 *
 * What "not cut" can mean is worth stating, because a panel pinned to the foot of a
 * scroller has to stand on something. It means two things, and both are asserted: the card
 * meets content through a fade band in its own box, so a row crossing that band dissolves
 * rather than ending at a rule; and whatever the band and the surface below it hide is
 * named in words, so a panel the card is standing on never reads as a panel that ended.
 */
/**
 * Let the pinned card finish answering the layout.
 *
 * What the card says it is covering is measured off its own surface after a scroll or a
 * resize, on an animation frame, and React paints the answer on the frame after that. Three
 * frames is the settle; without it a measurement taken in the same tick as the scroll reads
 * the line the previous scroll position wrote.
 */
async function settle(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((done) => {
        requestAnimationFrame(() =>
          requestAnimationFrame(() => requestAnimationFrame(() => done())),
        );
      }),
  );
}

async function decisionGeometry(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const need = <T extends Element>(selector: string): T => {
      const node = document.querySelector<T>(selector);
      if (node === null) throw new Error(`nothing on the page matches ${selector}`);
      return node;
    };
    const box = (node: Element) => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, height: rect.height, width: rect.width };
    };
    const onScreen = (rect: { top: number; bottom: number; height: number }): boolean =>
      rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;

    const card = need<HTMLElement>('.rh-web-decide');
    const surface = need<HTMLElement>('.rh-web-decide__surface');
    const strip = document.querySelector<HTMLElement>('.rh-web-source-strip');
    const stripShown = strip !== null && getComputedStyle(strip).display !== 'none';
    const style = getComputedStyle(card);

    // The fact rows the card can stand on, each with the panel it belongs to, so a covered
    // row can be checked against what the card says it is covering.
    const panels = Array.from(
      need<HTMLElement>('.rh-web-review-pane--end').querySelectorAll<HTMLElement>('section'),
    ).filter((section) => section.querySelector('h2') !== null && !section.contains(card));
    const rows = panels.flatMap((section) => {
      const title = section.querySelector('h2')?.textContent ?? '';
      return Array.from(section.querySelectorAll<HTMLElement>('dt, dd'))
        .map((row) => ({ panel: title, text: (row.textContent ?? '').trim().slice(0, 40), ...box(row) }))
        .filter((row) => row.height > 0);
    });

    return {
      view: window.innerHeight,
      card: box(card),
      surface: box(surface),
      bar: box(need('.rh-review-decision-bar')),
      advance: box(need('.rh-web-decide__advance')),
      fade: Number.parseFloat(style.paddingBlockStart),
      hairline: Number.parseFloat(style.borderTopWidth),
      wash: style.backgroundImage,
      more: (need('.rh-web-decide__more').textContent ?? '').trim(),
      strip: stripShown && strip !== null ? box(strip) : null,
      stripQuote: stripShown && strip !== null ? (strip.querySelector('.rh-web-quote')?.textContent ?? '') : '',
      stripAnchor: stripShown && strip !== null ? (strip.querySelector('.rh-source-anchor__target')?.textContent ?? '') : '',
      sourcePane: (() => {
        const quote = document.querySelector('.rh-web-source .rh-web-quote');
        const rendered = document.querySelector('.rh-pdf__canvas');
        return (quote !== null && onScreen(box(quote))) || (rendered !== null && onScreen(box(rendered)));
      })(),
      rows,
      barOnScreen: onScreen(box(need('.rh-review-decision-bar'))),
      advanceOnScreen: onScreen(box(need('.rh-web-decide__advance'))),
    };
  });
}

/** Everything the pinned decision must be true of, at whatever width it is measured. */
function expectSourceBesideDecision(
  geometry: Awaited<ReturnType<typeof decisionGeometry>>,
  where: string,
): void {
  // The card meets content through a fade, not through an opaque edge with a rule on it.
  expect(geometry.fade, `${where}: the decision card has no fade band`).toBeGreaterThanOrEqual(24);
  expect(geometry.hairline, `${where}: the card's own top edge is still a hairline`).toBe(0);
  expect(geometry.wash, `${where}: the fade band is not a fade`).toContain('linear-gradient');
  expect(
    geometry.surface.top - geometry.card.top,
    `${where}: the surface does not start below the fade`,
  ).toBeGreaterThanOrEqual(24);

  // The decision is in reach, and so is the switch that was under its fold.
  expect(geometry.barOnScreen, `${where}: the decision controls are off screen`).toBe(true);
  expect(
    geometry.advanceOnScreen,
    `${where}: the auto-advance switch needs scrolling inside a pinned panel`,
  ).toBe(true);
  expect(
    geometry.advance.top < geometry.bar.top,
    `${where}: auto-advance is not in the decision's first row`,
  ).toBe(true);

  // §26: whenever the decision is on screen, so is the source it is checked against —
  // the strip where the panes stack, the pane itself where they do not.
  if (geometry.strip === null) {
    expect(geometry.sourcePane, `${where}: the source pane is not beside the decision`).toBe(true);
  } else {
    expect(geometry.strip.height, `${where}: the pinned source strip is not drawn`).toBeGreaterThan(0);
    expect(geometry.stripQuote.length, `${where}: the strip carries no span`).toBeGreaterThan(0);
    expect(geometry.stripAnchor, `${where}: the strip does not name the page`).toContain('p.');
    expect(
      geometry.strip.bottom <= geometry.bar.top,
      `${where}: the decision covers the source strip`,
    ).toBe(true);
    expect(
      geometry.strip.top >= geometry.surface.top,
      `${where}: the strip is outside the pinned block`,
    ).toBe(true);
  }

  /*
   * No fact row is bisected.
   *
   * A row the card's *opaque* edge crosses must already have entered the fade — that is
   * what makes the meeting a dissolve rather than a cut, and it is the assertion that fails
   * if the band is ever removed or made shorter than a row of the definition list.
   */
  for (const row of geometry.rows) {
    if (row.top < geometry.surface.top && row.bottom > geometry.surface.top) {
      expect(
        row.top >= geometry.card.top,
        `${where}: "${row.text}" is cut by an opaque edge at ${geometry.surface.top}`,
      ).toBe(true);
    }
  }

  /*
   * And nothing disappears without being named. The card hides the band between its own
   * surface and its foot, so the panel a researcher was in the middle of when it went under
   * is the one the card's first line has to say. Rows further down that band are inside
   * panels below that one; naming every one of them would be a paragraph where a line is
   * what a quiet affordance is allowed to be.
   */
  const hidden = geometry.rows.filter(
    (row) => row.bottom > geometry.surface.top && row.top < geometry.card.bottom,
  );
  const first = hidden[0];
  if (first !== undefined) {
    expect(
      geometry.more,
      `${where}: the card hides "${first.text}" and names nothing`,
    ).toContain(first.panel);
  }
}

test('the source is beside the decision at every width the review is worked at', async ({ page, request }, info) => {
  await seedQueue(page, request);
  await page.getByRole('link', { name: /Metric result · W0001/ }).click();
  await expect(
    page.getByRole('heading', { name: 'Metric result · W0001', level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole('img', { name: /^page 4 of / })).toBeVisible();

  const viewport = page.viewportSize();
  const width = `${viewport?.width}×${viewport?.height}`;

  // At the project's own width, where a researcher lands. Where the panes sit side by side
  // the decision is pinned from the first frame; where they stack it is pinned once the
  // pane it belongs to is on screen, and a researcher still reading the source page has not
  // asked for it yet, so the arrival check is only made when the decision is actually up.
  await settle(page);
  const landed = await decisionGeometry(page);
  if (landed.barOnScreen) expectSourceBesideDecision(landed, `${width} on arrival`);
  await page.screenshot({ path: info.outputPath('review-source-beside-decision.png') });

  // And at the moment the decision is taken: `Verification` is the panel it is taken
  // against, so scrolling it into view is where the pinned card has the most to cover.
  await page.getByRole('heading', { name: 'Verification' }).scrollIntoViewIfNeeded();
  await settle(page);
  expectSourceBesideDecision(await decisionGeometry(page), `${width} at the verdict`);
  await page.screenshot({ path: info.outputPath('review-at-the-verdict.png') });

  // And at 1024×768, the window this defect was reported in, where the panes stack whatever
  // the project's own width is.
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.getByRole('heading', { name: 'Verification' }).scrollIntoViewIfNeeded();
  await settle(page);
  const stacked = await decisionGeometry(page);
  expect(
    stacked.strip,
    'the panes stack at 1024 and the source must travel with the decision',
  ).not.toBeNull();
  expectSourceBesideDecision(stacked, '1024×768 at the verdict');
  await page.screenshot({ path: info.outputPath('review-stacked-strip.png') });

  // The strip's control puts the page back on screen rather than opening anything over it.
  await page.getByRole('button', { name: /^Show page 4/ }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const rendered = await page.evaluate(() => {
    const canvas = document.querySelector('.rh-pdf__canvas');
    if (canvas === null) return null;
    const rect = canvas.getBoundingClientRect();
    return { top: rect.top, bottom: rect.bottom, view: window.innerHeight };
  });
  expect(rendered, 'the source page is not rendered').not.toBeNull();
  expect(
    (rendered as { top: number; bottom: number; view: number }).bottom > 0 &&
      (rendered as { top: number; bottom: number; view: number }).top <
        (rendered as { top: number; bottom: number; view: number }).view,
    'the strip’s control did not bring the page back on screen',
  ).toBe(true);
  await page.screenshot({ path: info.outputPath('review-strip-opened-page.png') });
});
