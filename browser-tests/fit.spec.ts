/**
 * Whether every destination fits the two small screens the cockpit claims to support.
 *
 * The rest of the suite proves the wide cases: 1920px for the reading measure, 1440px and
 * the shell's own 768px breakpoint for everything else. Nothing proved that the eleven
 * rail destinations survive a 1024x768 laptop or a 768x1024 tablet held upright, and
 * "fits" is four separate claims, none of which a unit test can make:
 *
 * 1. the page does not scroll sideways (`scrollWidth <= clientWidth` on the root);
 * 2. every visible control is at least 24x24 CSS px — WCAG 2.2 SC 2.5.8, with that
 *    criterion's own exception for a link inside a sentence, whose box is set by the line
 *    it sits in and not by the design;
 * 3. the page's `h1` is on screen before anybody scrolls, so the destination says which
 *    destination it is;
 * 4. axe finds nothing, with the landmark, heading and contrast rules of `axe.ts` on.
 *
 * Both Playwright projects run both screens: the same width in the dark theme and in the
 * light one are different colour pairs to `color-contrast`, and the shell's narrow layout
 * turns on below 960px, so 1024 and 768 are the two sides of that switch.
 *
 * The walk opens a session first, and that is deliberate rather than incidental: the rail's
 * session list only has a *selected* row once a session exists, and muted ink on the
 * selected row's tint is the pair that failed `color-contrast` at 3.99:1 in the dark theme
 * and forced the composer spec to scope its axe run to one component. A walk over an empty
 * project would never repaint that row and would never see it again.
 */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page, TestInfo } from '@playwright/test';
import { axeViolations } from './axe';

/**
 * The eleven rail destinations of PRODUCT §26, conversation first. `''` is the root.
 *
 * `label` is the word the rail calls the destination — and, below the shell's breakpoint,
 * the word the collapsed bar has to call it too, because the rail saying it is behind a
 * button by then. It is written out here rather than read from the app so that a label
 * silently changing on one of the two surfaces fails this walk.
 */
const DESTINATIONS = [
  { path: '', name: 'conversation', label: 'Conversation' },
  { path: 'overview', name: 'overview', label: 'Overview' },
  { path: 'review', name: 'review', label: 'Review inbox' },
  { path: 'conflicts', name: 'conflicts', label: 'Conflicts' },
  { path: 'stale', name: 'stale', label: 'Stale' },
  { path: 'corpus', name: 'corpus', label: 'Corpus' },
  { path: 'claims', name: 'claims', label: 'Claims' },
  { path: 'questions', name: 'questions', label: 'Questions' },
  { path: 'synthesis', name: 'synthesis', label: 'Synthesis' },
  { path: 'taxonomy', name: 'taxonomy', label: 'Taxonomy' },
  { path: 'manuscript', name: 'manuscript', label: 'Manuscript' },
];

/** A laptop, and a tablet held upright. The shell's drawer breakpoint (960px) is between. */
const SCREENS = [
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
];

/** WCAG 2.2 SC 2.5.8, and the token the Design System sizes its controls against. */
const TARGET_MIN = 24;

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/**
 * A registered project with one session open, and the conversation's own URL.
 *
 * The session is what puts a selected row in the rail's list on every screen the walk
 * visits, and the query — `?session=CS0001` — is how the conversation route is addressed,
 * so the walk reloads into the session rather than into an empty root.
 */
async function openWorkspace(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
  name: string,
  narrow: boolean,
): Promise<{ workspace: string; conversation: string }> {
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
  await expect(page.getByRole('main', { name: 'Research workspace' })).toBeVisible();
  const workspace = new URL(page.url()).pathname.replace(/\/$/, '');

  // Below the shell's breakpoint the rail — and the control that opens a session — is a
  // drawer, so it has to be opened, and closed again before anything is measured.
  if (narrow) await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  await page.getByRole('button', { name: 'New session', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'New session' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Create session', exact: true }).click();
  await expect(dialog).toBeHidden();
  if (narrow) {
    const close = page.getByRole('button', { name: 'Close project navigation' });
    if (await close.isVisible()) await close.click();
  }
  await page.waitForURL(/\?session=/);
  return { workspace, conversation: `${workspace}/${new URL(page.url()).search}` };
}

interface FitReport {
  /** How many px the document scrolls sideways. Zero or less is a fit. */
  overflow: number;
  /** One line per control smaller than the floor, with the size it came out at. */
  undersized: string[];
}

/**
 * The geometry of one route, measured in the page.
 *
 * "Visible" is the browser's own answer (`checkVisibility`) plus a non-empty box, so a
 * control in a closed drawer, behind `hidden`, or collapsed to nothing is not held to a
 * pointer-target floor it is not a pointer target for.
 */
async function measure(page: Page, min: number): Promise<FitReport> {
  return page.evaluate((floor) => {
    const root = document.documentElement;
    const undersized: string[] = [];

    /** Enough of an element to find it again: tag, id or class, and its accessible-ish name. */
    const describe = (element: Element): string => {
      const id = element.id ? `#${element.id}` : '';
      const classes = element.classList.length > 0 ? `.${[...element.classList].join('.')}` : '';
      const label =
        element.getAttribute('aria-label') ?? (element.textContent ?? '').trim().slice(0, 40);
      return `${element.tagName.toLowerCase()}${id}${classes}${label ? ` ("${label}")` : ''}`;
    };

    for (const element of document.querySelectorAll('button, a, [role="tab"]')) {
      if (!element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;

      // SC 2.5.8's "inline" exception: a link in a run of text is sized by the sentence
      // around it, and padding it to 24px would break the paragraph it belongs to.
      const style = getComputedStyle(element);
      if (element.tagName === 'A' && style.display.startsWith('inline')) {
        const parent = element.parentElement;
        const own = (element.textContent ?? '').trim();
        if (parent && (parent.textContent ?? '').trim() !== own) continue;
      }

      if (box.width < floor || box.height < floor) {
        undersized.push(`${describe(element)} is ${Math.round(box.width)}x${Math.round(box.height)}`);
      }
    }

    return { overflow: root.scrollWidth - root.clientWidth, undersized };
  }, min);
}

for (const screen of SCREENS) {
  const label = `${screen.width}x${screen.height}`;

  test(`every destination fits a ${label} screen`, async ({ page, request }, info) => {
    // Eleven routes, each with an axe pass, a measurement and (at 768px) a screenshot.
    test.setTimeout(300_000);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    // The viewport is set before the project is created, so the session is opened through
    // whichever layout this screen actually has.
    await page.setViewportSize(screen);
    const { workspace, conversation } = await openWorkspace(
      page,
      request,
      info,
      `Fit study ${label}`,
      screen.width <= 960,
    );

    for (const destination of DESTINATIONS) {
      const url = destination.path === '' ? conversation : `${workspace}/${destination.path}`;
      await page.goto(url);

      // Before anything is measured, the destination has to have arrived: its own `h1`,
      // in the viewport, without a scroll.
      const heading = page.getByRole('heading', { level: 1 }).first();
      await expect(heading, `${destination.name} must have a level-1 heading`).toBeVisible();
      await expect(
        heading,
        `${destination.name} must show its heading at ${label} before any scrolling`,
      ).toBeInViewport();

      const report = await measure(page, TARGET_MIN);
      expect(
        report.overflow,
        `${destination.name} scrolls ${report.overflow}px sideways at ${label}`,
      ).toBeLessThanOrEqual(0);
      expect(
        report.undersized,
        `${destination.name} has controls under ${TARGET_MIN}px at ${label}`,
      ).toEqual([]);

      expect(await axeViolations(page), `${destination.name} at ${label}`).toEqual([]);

      if (screen.width === 768) {
        // The rail is a drawer at this width, so the bar is the only thing on screen that
        // can say where you are. It says both halves: the project, and this destination.
        const bar = page.locator('header.rh-app-shell__bar');
        await expect(
          bar,
          `${destination.name} must be named in the collapsed bar at ${label}`,
        ).toContainText(destination.label);
        await expect(bar.locator('.rh-app-shell__bar-context')).not.toBeEmpty();

        // And it says it whole. The name beside it is the half that gives up room, so a
        // clipped destination is a defect rather than a narrow window.
        const clipped = await bar
          .locator('.rh-app-shell__bar-page')
          .evaluate((node) => node.scrollWidth - node.clientWidth);
        expect(
          clipped,
          `${destination.name} is cut off in the collapsed bar at ${label}`,
        ).toBeLessThanOrEqual(0);

        await page.screenshot({
          path: info.outputPath(`${destination.name}-768.png`),
          fullPage: true,
        });
      }
    }

    expect(errors).toEqual([]);
  });
}
