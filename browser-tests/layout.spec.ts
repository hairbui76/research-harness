/**
 * Whether the cockpit's layout checks that its own content fits.
 *
 * Three things this suite measures rather than assumes, because none of them can be seen
 * without a browser: prose holds a reading measure at a width no unit test ever renders;
 * six inspector tabs are all reachable inside a pane about a third as wide as they are; and
 * the two places that offer project lifecycle actions offer the same ones, in the same
 * order, under the same words.
 *
 * Both Playwright projects run all of it, and the measure test resizes to 1920x1080 inside
 * the test, because that is the width the critique measured 232-character lines at.
 */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Locator, Page, TestInfo } from '@playwright/test';
// One run below scopes axe to `.rh-message` rather than the route, so it builds its own;
// `axeViolations` is the page-level gate every other assertion in this file uses.
import { axeViolations } from './axe';

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** A registered project, opened at its own URL. Every test here needs one of its own. */
async function openWorkspace(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
  name: string,
): Promise<string> {
  const response = await request.get('/__test__/bootstrap');
  expect(response.ok()).toBeTruthy();
  const { nonce, parent } = await response.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`${name} ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();

  await page.waitForURL(/\/projects\/[^/?#]+/);
  // The URL changes before the registry has the new project, and until it does the shell
  // still renders Project Home under a project URL. Waiting for the workspace's own main
  // landmark is what makes everything after this point about the workspace.
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();
  return new URL(page.url()).pathname.replace(/\/$/, '');
}

/**
 * How many characters wide a run of text actually is.
 *
 * `ch` is the width of a zero in the element's own font, so a probe that inherits the
 * element's typography converts its measured width into the unit the craft floor is
 * written in. Dividing pixels by the font size would answer in `em` instead, which is a
 * different and looser number.
 */
async function measureInCharacters(page: Page, selector: string): Promise<number> {
  return page.evaluate((css) => {
    const element = document.querySelector(css);
    if (!(element instanceof HTMLElement)) throw new Error(`no element matched ${css}`);
    const probe = document.createElement('span');
    probe.style.display = 'inline-block';
    probe.style.inlineSize = '1ch';
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    element.appendChild(probe);
    const oneCharacter = probe.getBoundingClientRect().width;
    probe.remove();
    return element.getBoundingClientRect().width / oneCharacter;
  }, selector);
}

/** The labels of the menu a "Project actions" trigger opens, then closed again. */
async function projectActionLabels(page: Page, trigger: Locator): Promise<string[]> {
  await trigger.click();
  const items = page.getByRole('menuitem');
  await expect(items.first()).toBeVisible();
  const labels = await items.allInnerTexts();
  await page.keyboard.press('Escape');
  await expect(items.first()).toBeHidden();
  return labels.map((label) => label.trim());
}

/** Below the shell's breakpoint the rail is a drawer, so it has to be opened first. */
async function openRail(page: Page): Promise<void> {
  const opener = page.getByRole('button', { name: 'Project navigation', exact: true });
  if (await opener.isVisible()) await opener.click();
}

test('prose holds a reading measure on a 1920px screen while the page does not overflow', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const workspace = await openWorkspace(page, request, info, 'Measure study');
  await page.setViewportSize({ width: 1920, height: 1080 });

  await page.goto(`${workspace}/corpus`);
  await expect(page.getByRole('heading', { level: 1, name: 'Corpus' })).toBeVisible();

  const description = await measureInCharacters(page, '.rh-full-page__description');
  // A cap that produced nothing would also be under 75; the floor says it is real text.
  expect(description, 'the page description must be a measured run of text').toBeGreaterThan(20);
  expect(
    description,
    `the page description ran ${description.toFixed(0)} characters at 1920px`,
  ).toBeLessThanOrEqual(75);

  // The table beside it is scanned, not read, and keeps the width the page gives it.
  const wide = await page.evaluate(() => {
    const content = document.querySelector('.rh-full-page__content');
    const prose = document.querySelector('.rh-full-page__description');
    if (!(content instanceof HTMLElement) || !(prose instanceof HTMLElement)) return null;
    return {
      content: content.getBoundingClientRect().width,
      prose: prose.getBoundingClientRect().width,
    };
  });
  expect(wide).not.toBeNull();
  expect(wide!.prose, 'prose must be capped well inside the page body').toBeLessThan(
    wide!.content * 0.8,
  );

  expect(await axeViolations(page), 'the corpus page at 1920px').toEqual([]);

  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(fits, 'a 1920px window must not overflow horizontally').toBeTruthy();

  await page.screenshot({ path: info.outputPath('measure-1920.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('every inspector tab is reachable from the keyboard at both widths', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await openWorkspace(page, request, info, 'Inspector study');

  for (const width of [1920, 768]) {
    await page.setViewportSize({ width, height: 1024 });

    // "Show" exists only while the inspector is closed, so its presence is the question.
    const show = page.getByRole('button', { name: 'Show the research inspector', exact: true });
    if ((await show.count()) > 0) await show.first().click();

    const inspector = page.getByRole('region', { name: 'Research inspector' });
    await expect(inspector).toBeVisible();
    const tabs = inspector.getByRole('tab');
    await expect(tabs, `six tabs at ${width}px`).toHaveCount(6);

    await tabs.first().focus();
    for (let index = 0; index < 6; index += 1) {
      const tab = tabs.nth(index);
      await expect(tab, `tab ${index} must hold focus at ${width}px`).toBeFocused();
      // Clipped by the strip counts as out of the viewport, which is the point.
      await expect(tab, `tab ${index} must be in view at ${width}px`).toBeInViewport();
      if (index < 5) await page.keyboard.press('ArrowRight');
    }

    /*
     * Reachable is not the same as legible. Six tabs measuring about 734px used to live in a
     * 22rem strip, so at 1920 the last visible label read "ew inbox" and two tabs were
     * behind a chevron at every width. The strip spends vertical room instead: nothing
     * scrolls sideways, and every tab draws its whole label inside it.
     */
    const clipped = await inspector.evaluate((node) => {
      const list = node.querySelector('.rh-tabs__list') as HTMLElement;
      const out: string[] = [];
      if (list.scrollWidth > list.clientWidth + 1) {
        out.push(`the strip scrolls by ${list.scrollWidth - list.clientWidth}px`);
      }
      const box = list.getBoundingClientRect();
      for (const tab of Array.from(node.querySelectorAll('[role="tab"]')) as HTMLElement[]) {
        const rect = tab.getBoundingClientRect();
        if (rect.left < box.left - 1 || rect.right > box.right + 1) {
          out.push(`${tab.textContent?.trim()} is cut off`);
        }
        if (tab.scrollWidth > tab.clientWidth + 1) out.push(`${tab.textContent?.trim()} is clipped`);
      }
      return out;
    });
    expect(clipped, `the inspector strip at ${width}px`).toEqual([]);

    expect(await axeViolations(page), `axe at ${width}px`).toEqual([]);

    const fits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(fits, `the conversation must not overflow sideways at ${width}px`).toBeTruthy();

    await page.screenshot({ path: info.outputPath(`inspector-${width}.png`), fullPage: true });
  }

  expect(errors).toEqual([]);
});

/**
 * The one surface sixty screenshots did not hold: a transcript row.
 *
 * 2G's answer to "eight controls per message" was one toolbar with a *More actions*
 * overflow behind it, and nothing in the suite could photograph one, because every route to
 * an assistant turn runs through `session.send` and a model provider. `/__test__/session-
 * with-turn` seeds one through the daemon's own offline selector, so the row here is the
 * row the code writes rather than a fixture written to look like it.
 */
test('a transcript row carries one toolbar, with the rest behind More actions', async ({
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

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(conversation.conversation_url);
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();

  const answer = page.locator('.rh-message[data-role="assistant"]').first();
  await expect(answer).toBeVisible();

  // One row of controls, not eight loose buttons: what stays visible is the short list,
  // and everything else is one press away.
  const toolbar = answer.getByRole('group', { name: /^Actions for / });
  await expect(toolbar).toBeVisible();
  const visible = await toolbar.getByRole('button').allInnerTexts();
  expect(
    visible.length,
    `a message row shows ${visible.length} controls: ${visible.join(', ')}`,
  ).toBeLessThanOrEqual(4);

  // The act that turns an answer into scientific state is the one with a name on it.
  await expect(toolbar.getByRole('button', { name: 'Promote…' })).toBeVisible();

  // The answer's own prose holds a reading measure. It ran about 114 characters at 1440,
  // because the cap the package puts on a message's prose is written for a host that
  // renders bare elements and this renderer wraps its output in `.rh-md`.
  const line = await measureInCharacters(page, '.rh-message[data-role="assistant"] .rh-md > p');
  expect(line, 'the answer must be a measured run of text').toBeGreaterThan(20);
  expect(line, `a transcript line ran ${line.toFixed(0)} characters`).toBeLessThanOrEqual(75);

  await toolbar.getByRole('button', { name: 'More actions' }).click();
  const overflow = page.getByRole('menu', { name: /^More actions for / });
  await expect(overflow).toBeVisible();
  await expect(overflow.getByRole('menuitem', { name: 'Inspect' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('message-overflow.png'), fullPage: true });
  await page.keyboard.press('Escape');

  expect(await axeViolations(page), 'a transcript row and its overflow').toEqual([]);

  expect(errors).toEqual([]);
});

test('the rail names its three groups without adding a tab stop', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await openWorkspace(page, request, info, 'Grouping study');
  await openRail(page);

  // Roadmap 3L, option A: three visible headings over ten of the twelve destinations, and
  // the two ways in above them with no heading at all. Evidence joined "The record" in wave
  // six, between Corpus and Claims where PRODUCT §26 lists it, so that group is one longer
  // than it was; the grouping itself is unchanged.
  for (const [name, labels] of [
    ['Waiting', ['Review inbox', 'Conflicts', 'Stale']],
    ['The record', ['Corpus', 'Evidence', 'Claims', 'Questions', 'Taxonomy']],
    ['Outputs', ['Synthesis', 'Manuscript']],
  ] as const) {
    const group = page.getByRole('list', { name });
    await expect(group, `the rail must name the ${name} group`).toBeVisible();
    await expect(group.locator('.rh-project-rail__nav-label')).toHaveText([...labels]);
  }

  /*
   * What only a browser can say about the headings.
   *
   * Each is a paragraph that names its list, so a screen reader announces the word on
   * entering the run and Tab never lands on it — the drawer path of `app.spec.ts` reaches
   * the project switcher first, and would not if a heading were focusable. And the craft
   * floor bans the uppercase micro-label: the word renders in the case it was written in,
   * in the muted ink the palette's "Go to" heading uses.
   */
  const headings = await page.evaluate(() => {
    const rail = document.querySelector('.rh-project-rail') as HTMLElement;
    const muted = getComputedStyle(document.documentElement)
      .getPropertyValue('--rh-text-muted')
      .trim();
    const probe = document.createElement('span');
    probe.style.color = `var(--rh-text-muted)`;
    rail.appendChild(probe);
    const mutedRGB = getComputedStyle(probe).color;
    probe.remove();
    return {
      words: [...rail.querySelectorAll('.rh-project-rail__nav-heading')].map((node) => ({
        text: (node.textContent ?? '').trim(),
        tag: node.tagName,
        names: node.id !== '' && document.querySelector(`[aria-labelledby="${node.id}"]`) !== null,
        // Only a control the rail itself owns counts: below the shell's breakpoint the rail
        // is inside a drawer parked at `tabindex="-1"`, which is not a tab stop.
        focusable: (() => {
          const owner = node.closest('a[href], button, [tabindex]:not([tabindex="-1"])');
          return owner !== null && rail.contains(owner);
        })(),
        transform: getComputedStyle(node).textTransform,
        muted: getComputedStyle(node).color === mutedRGB,
        size: Number.parseFloat(getComputedStyle(node).fontSize),
      })),
      mutedDeclared: muted !== '',
      // Every tab stop inside the rail, as its accessible text.
      stops: [...rail.querySelectorAll('a[href], button, [tabindex]:not([tabindex="-1"])')].map(
        (node) => (node.textContent ?? '').trim(),
      ),
    };
  });

  expect(headings.words.map((word) => word.text)).toEqual(['Waiting', 'The record', 'Outputs']);
  for (const word of headings.words) {
    expect(word.tag, `${word.text} must be text, not a control`).toBe('P');
    expect(word.names, `${word.text} must name its own list`).toBe(true);
    expect(word.focusable, `${word.text} must not sit inside a control`).toBe(false);
    expect(word.transform, `${word.text} must not be an uppercase micro-label`).toBe('none');
    expect(word.muted, `${word.text} must take the muted ink`).toBe(true);
    expect(word.size, `${word.text} must be at label size`).toBeLessThan(14);
  }
  expect(headings.mutedDeclared).toBe(true);
  for (const name of ['Waiting', 'The record', 'Outputs']) {
    expect(headings.stops, `${name} must add no tab stop`).not.toContain(name);
  }

  await page.screenshot({ path: info.outputPath('rail-groups.png'), fullPage: true });
  expect(await axeViolations(page), 'the workspace with a grouped rail').toEqual([]);
  expect(errors).toEqual([]);
});

test('the rail and Project Home offer the same project actions in the same words', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await openWorkspace(page, request, info, 'Vocabulary study');

  // A workspace with no session open. The composer has nothing to send, so it offers no
  // model trigger either: one that names a model over a silent destination line is what
  // the capture of this screen caught, and it is the one regression removing the
  // EXTERNAL/LOCAL tag from the trigger must not cause.
  await expect(page.getByRole('button', { name: /^Model:/ })).toHaveCount(0);
  await expect(page.locator('.rh-composer__destination')).toHaveCount(0);

  await openRail(page);
  const fromRail = await projectActionLabels(
    page,
    page.getByRole('button', { name: 'Project actions', exact: true }),
  );
  expect(fromRail).toEqual([
    'Show in file manager',
    'Locate folder',
    'Rename',
    'Forget project',
  ]);
  await page.screenshot({ path: info.outputPath('rail-actions.png'), fullPage: true });

  /*
   * A project with no sessions opens no void.
   *
   * The empty session list used to be the rail's growing element, so about a third of the
   * rail's height sat empty between it and the navigation. The list takes its content
   * height, the destinations follow it, and the free space goes under them to the footer.
   */
  const rail = await page.evaluate(() => {
    const gap = (a: Element | null, b: Element | null): number =>
      a === null || b === null
        ? Number.NaN
        : b.getBoundingClientRect().top - a.getBoundingClientRect().bottom;
    const sessions = document.querySelector('.rh-project-rail__sessions');
    const nav = document.querySelector('.rh-project-rail__nav');
    const foot = document.querySelector('.rh-project-rail__foot');
    return {
      beforeNav: gap(sessions, nav),
      navAboveFoot:
        nav !== null && foot !== null
          ? nav.getBoundingClientRect().bottom <= foot.getBoundingClientRect().top
          : false,
      footAtTheBottom:
        foot !== null && document.querySelector('.rh-project-rail') !== null
          ? Math.abs(
              foot.getBoundingClientRect().bottom -
                (document.querySelector('.rh-project-rail') as HTMLElement).getBoundingClientRect()
                  .bottom,
            )
          : Number.NaN,
    };
  });
  expect(rail.beforeNav, `${rail.beforeNav}px of empty rail above the navigation`).toBeLessThan(24);
  expect(rail.navAboveFoot, 'the destinations sit above the provider footer').toBe(true);
  expect(rail.footAtTheBottom, 'the footer stays at the rail’s bottom edge').toBeLessThan(24);

  // Project Home is reached the way a researcher reaches it. A fresh load of `/` would
  // reopen the last project instead (spec §4.2), which is the point of that rule.
  await page.getByRole('button', { name: /^Project: .* Switch project$/ }).click();
  await page.getByRole('menuitem', { name: 'All projects', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  const list = page.getByRole('list', { name: 'Registered projects' });
  await expect(list).toBeVisible();
  // The registry is cut into runs by how recently each project was last opened and is
  // windowed, so it is one sequence: a run's naming line, then the workspaces it names.
  // The first row is the first item of that sequence holding a workspace card.
  const row = list.getByRole('listitem').filter({ has: page.locator('.rh-projects__card') }).first();
  /*
   * One visible act per row, and it is the workspace's own name.
   *
   * Changed on purpose, twice. It was `toHaveText(['Open', 'Project actions'])` until
   * printing the second name on every row made the pair read twice down a long registry,
   * so those words moved into the trigger's accessible name. Then Open went too: a filled
   * button on every row of a registry of forty-six is the page's loudest emphasis spent
   * forty-six times, and the name a researcher is already reading is what they reach for.
   * So the row's act is a link, and its one button is the overflow.
   */
  await expect(row.getByRole('link')).toHaveCount(1);
  await expect(row.getByRole('button')).toHaveText(['']);
  await expect(row.getByRole('button', { name: 'Project actions', exact: true })).toBeVisible();
  await expect(row.getByText('Project actions')).toHaveCount(0);

  const fromHome = await projectActionLabels(
    page,
    row.getByRole('button', { name: 'Project actions', exact: true }),
  );
  expect(fromHome, 'Project Home must offer the rail’s actions verbatim').toEqual(fromRail);

  expect(await axeViolations(page), 'Project home with its actions menu').toEqual([]);

  await page.screenshot({ path: info.outputPath('project-home-actions.png'), fullPage: true });
  expect(errors).toEqual([]);
});

interface ChipBox {
  selector: string;
  found: boolean;
  top?: number;
  bottom?: number;
  border?: number;
  height?: number;
  line?: number;
}

/** One count pill's own box: what is inside its border, and what its height came from. */
async function measureChip(page: Page, selector: string): Promise<ChipBox> {
  return page.evaluate((wanted): ChipBox => {
    const node = document.querySelector(wanted);
    if (!(node instanceof HTMLElement)) return { selector: wanted, found: false };
    const style = getComputedStyle(node);
    return {
      selector: wanted,
      found: true,
      top: Number.parseFloat(style.paddingTop),
      bottom: Number.parseFloat(style.paddingBottom),
      border: Number.parseFloat(style.borderTopWidth),
      // The rule the chips keep: the box is the text's own line, plus the inset and border.
      height: node.getBoundingClientRect().height,
      line: Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize),
    };
  }, selector);
}

/**
 * The count pills have an inside.
 *
 * The browser detector's `cramped-padding` findings on the third critique were the rail's
 * and the inspector's count chips: a numeral with a 1px border on both block edges and no
 * inset between them, which is a pill drawn as a box around a glyph. The rule the stylesheet
 * states — height comes from the text, because neither a 36px nav row nor a strip holding
 * six tabs can afford a count that sets the row height — stays; what changes is that there
 * is now one hairline's worth of room inside the border.
 */
test('the rail and inspector count chips are inset from their own border', async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  /*
   * A project with a queue in it, because the rail draws a count only where there is one to
   * draw: `Layout` attaches a count to a destination when the daemon reports more than zero
   * waiting there, so a project created seconds ago has no chip to measure. The inspector's
   * tabs count from the overview and carry theirs either way.
   */
  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/review-queue', { timeout: 60_000 });
  expect(seeded.ok()).toBeTruthy();
  const queue = await seeded.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(new URL(queue.review_url, page.url()).pathname.replace(/\/review$/, ''));
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();

  // The rail first. Below the breakpoint it is a drawer over the page, so it is measured
  // while it is open and closed again before anything behind it is asked for.
  await openRail(page);
  await expect(
    page.locator('.rh-project-rail__nav-count').first(),
    'the seeded queue must give the rail a count to draw',
  ).toBeVisible();
  const rail = await measureChip(page, '.rh-project-rail__nav-count');
  await page.keyboard.press('Escape');

  const show = page.getByRole('button', { name: 'Show the research inspector', exact: true });
  if ((await show.count()) > 0) await show.first().click();
  await expect(page.getByRole('region', { name: 'Research inspector' })).toBeVisible();
  await expect(page.locator('.rh-research-inspector__tab-count').first()).toBeVisible();
  const inspector = await measureChip(page, '.rh-research-inspector__tab-count');

  for (const chip of [rail, inspector]) {
    expect(chip.found, `${chip.selector} must be on screen to be measured`).toBe(true);
    expect(chip.border, `${chip.selector} draws the hairline this inset answers`).toBeGreaterThan(0);
    expect(
      Math.min(chip.top!, chip.bottom!),
      `${chip.selector} ran ${chip.top}px/${chip.bottom}px of block inset inside a border`,
    ).toBeGreaterThanOrEqual(1);
    expect(
      chip.height!,
      `${chip.selector} must still take its height from the text`,
    ).toBeLessThanOrEqual(chip.line! + 2 * (chip.top! + chip.border!) + 1);
  }

  await page.screenshot({ path: info.outputPath('count-chips.png'), fullPage: true });
  expect(errors).toEqual([]);
});
