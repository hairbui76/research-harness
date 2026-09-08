/**
 * Whether the manuscript route is usable on the two small screens the cockpit supports.
 *
 * The fit sweep proves the route does not overflow and shows its `h1`; it says nothing
 * about whether the workspace inside that frame can be worked in. Wave three's finish
 * review and the second critique both logged what a capture at 768px shows: three panes
 * dividing a width none of them can hold, an editor column narrow enough to clip its own
 * toolbar, and the build-and-audit inspector pressed against the bottom edge.
 *
 * The trap is that the viewport is the wrong ruler for this route. A 1024x768 laptop is
 * "wide" to a media query, and the shell then spends 16rem of it on the project rail, so
 * the manuscript workspace gets about 768px of inline size on *both* screens below. Every
 * measurement here is therefore taken on the workspace and its panes rather than on the
 * window, which is the same rule the research inspector and the full page already follow.
 *
 * What it holds the route to, at 768x1024 and at 1024x768:
 *
 * 1. the frame says where you are and what you are editing - the `h1`, the manuscript path
 *    and the toolbar are all in the viewport before anybody scrolls;
 * 2. the primary act is one of them: Compile is in the viewport, not below a fold;
 * 3. the audit is reachable, and the file tree's entry file is reachable;
 * 4. the editor is wide enough to edit LaTeX in - 40 characters of its own font, which is
 *    the floor below which a wrapped equation stops being readable;
 * 5. no pane is narrower than its own content, so nothing is clipped or scrolls sideways
 *    inside the page;
 * 6. axe finds nothing, with the landmark, heading and contrast rules of `axe.ts` on.
 */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';
import { axeViolations } from './axe';

/** A tablet held upright, and a laptop. Both leave the workspace about 768px of width. */
const SCREENS = [
  { width: 768, height: 1024, label: '768' },
  { width: 1024, height: 768, label: '1024' },
];

/**
 * The narrowest run of LaTeX worth editing.
 *
 * Below about 40 characters a wrapped `\begin{tabular}` row or an inline equation stops
 * being one readable line, and the editor is no longer the place the work happens.
 */
const EDITOR_MIN_CHARACTERS = 40;

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
    // The workspace remembers pane sizes and whether the inspector is open. A run that
    // inherited either would be measuring a previous run's drag, not the layout as it
    // arrives, so every screen here starts from the layout a first visit gets.
    localStorage.removeItem('rh.manuscript.columns');
    localStorage.removeItem('rh.manuscript.rows');
    localStorage.removeItem('rh.manuscript.inspector');
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

/** A registered project whose `manuscript/` already holds source, at its own URL. */
async function openManuscript(page: Page, request: APIRequestContext): Promise<void> {
  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce } = await bootstrap.json();
  const seeded = await request.post('/__test__/manuscript-project', { timeout: 60_000 });
  expect(seeded.ok()).toBeTruthy();
  const project = await seeded.json();

  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();
  await page.goto(project.manuscript_url);
  await expect(page.getByRole('heading', { level: 1, name: 'Manuscript' })).toBeVisible();
}

interface PaneReport {
  /** How wide the manuscript workspace itself is, which is the ruler the layout uses. */
  workspace: number;
  /** One line per pane whose content is wider than the pane, with the overshoot. */
  clipped: string[];
  /** How many px the document scrolls sideways. Zero or less is a fit. */
  overflow: number;
}

/**
 * What each pane holds against what it was given, measured in the page.
 *
 * `.rh-pane` hides its overflow and the workspace's own panes scroll theirs, so neither
 * shows up as a scrollbar on the document: the only way to see a pane too narrow for its
 * content is to compare its scroll width with its client width, one pane at a time.
 */
async function measurePanes(page: Page): Promise<PaneReport> {
  return page.evaluate(() => {
    const workspace = document.querySelector('.rh-manuscript-workspace') as HTMLElement | null;
    const clipped: string[] = [];
    const selectors = ['.rh-pane', '.rh-source-editor__toolbar', '.rh-manuscript-workspace__bar'];
    for (const selector of selectors) {
      for (const node of Array.from(document.querySelectorAll(selector)) as HTMLElement[]) {
        if (!node.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
        const overshoot = node.scrollWidth - node.clientWidth;
        if (overshoot > 1) {
          const name = [...node.classList].join('.');
          clipped.push(`.${name} holds ${overshoot}px more than it was given`);
        }
      }
    }
    return {
      workspace: workspace === null ? 0 : workspace.getBoundingClientRect().width,
      clipped,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
}

/**
 * How many characters wide the editor's text area is, in the editor's own font.
 *
 * `ch` is the width of a zero in the element's font, so a probe that inherits the editor's
 * typography answers in the unit the craft floor is written in. CodeMirror's content
 * element is the one that matters; the frame around it is set in the UI font.
 */
async function editorCharacters(page: Page): Promise<number> {
  return page.evaluate(() => {
    const element = (document.querySelector('.cm-content') ??
      document.querySelector('.rh-source-editor__surface')) as HTMLElement | null;
    if (element === null) throw new Error('the source editor has no surface');
    const probe = document.createElement('span');
    probe.style.display = 'inline-block';
    probe.style.inlineSize = '1ch';
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    element.appendChild(probe);
    const oneCharacter = probe.getBoundingClientRect().width;
    probe.remove();
    return element.getBoundingClientRect().width / oneCharacter;
  });
}

for (const screen of SCREENS) {
  test(`the manuscript can be worked in at ${screen.width}x${screen.height}`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    await page.setViewportSize({ width: screen.width, height: screen.height });
    await openManuscript(page, request);

    // The entry file opens on its own, so the editor is holding a buffer before anything
    // below measures it.
    const frame = page.getByRole('region', { name: 'Manuscript source: main.tex' });
    await expect(frame, 'the entry file must open on arrival').toBeVisible();

    // 1. The frame: which destination this is, which file is open, and the toolbar.
    const heading = page.getByRole('heading', { level: 1, name: 'Manuscript' });
    await expect(heading, `the h1 must be in view at ${screen.label}`).toBeInViewport();
    const path = page.locator('.rh-manuscript-workspace__bar').getByText(/manuscript\/main\.tex$/);
    await expect(path, `the manuscript path must be in view at ${screen.label}`).toBeInViewport();
    await expect(
      page.getByRole('button', { name: 'Suggest…' }),
      `the workspace toolbar must be in view at ${screen.label}`,
    ).toBeInViewport();

    /*
     * 1b. The toolbar spends no room on a state nobody asked about.
     *
     * Save is an act with nothing to act on while the buffer's own chip reads "Saved", and
     * the reason there is no SyncTeX map was a permanent row above the editor whether or not
     * anyone ever tried to jump — two lines of the third critique's minor observations, and
     * on this route the width they cost is the whole point.
     */
    const save = page.getByRole('button', { name: 'Save' });
    await expect(save, `Save offers nothing on a saved buffer at ${screen.label}`).toBeDisabled();
    const because = await save.getAttribute('aria-describedby');
    expect(because, 'a disabled Save says why, at the control').toBeTruthy();
    await expect(page.locator(`#${because}`)).toHaveText('Saved');
    await expect(
      page.locator('.rh-source-editor__note'),
      'nothing states an absence before it is asked about',
    ).toHaveCount(0);

    // 2. The primary act, in the viewport before anybody scrolls for it.
    const compile = page.getByRole('button', { name: 'Compile' });
    await expect(compile, `Compile must exist at ${screen.label}`).toBeVisible();
    await expect(
      compile,
      `Compile must be in the viewport at ${screen.label} before any scrolling`,
    ).toBeInViewport();

    // 3a. The audit, reachable without hunting. Two things are pinned in the frame: the
    // bar's own control, whose name is the panel's, and the tab that opens it. Choosing it
    // has to put the audit's own lists in the viewport, not the top of a 300px strip whose
    // headings are below the bottom edge.
    const barControl = page.getByRole('button', { name: 'Show the build and audit panel' });
    await expect(
      barControl,
      `the bar's inspector control must be in view at ${screen.label}`,
    ).toBeInViewport();
    // Below the breakpoint the control selects a view rather than expanding a pane, so it
    // is a toggle and says whether the inspector is the view on show.
    await expect(barControl).toHaveAttribute('aria-pressed', 'false');
    const auditTab = page.getByRole('tab', { name: 'Inspector', exact: true });
    await expect(
      auditTab,
      `the way into the audit must be on screen at ${screen.label}`,
    ).toBeInViewport();
    await auditTab.click();
    await expect(page.getByRole('region', { name: 'Build and audit' })).toBeVisible();
    // The tab and the bar are two ways to one view, so the bar reports what the tab did:
    // it can never offer to hide an inspector that is already the view on show.
    await expect(
      barControl,
      `the bar control must read the inspector's own state at ${screen.label}`,
    ).toHaveAttribute('aria-pressed', 'true');
    const diagnostics = page.getByRole('heading', { name: /^Compiler diagnostics/ }).first();
    await expect(
      diagnostics,
      `the audit's own lists must be in view once it is chosen at ${screen.label}`,
    ).toBeInViewport();

    /*
     * Reachable is not the same as readable.
     *
     * A finding row puts a short kind and a fixed file position beside a long message. In
     * a panel this narrow the fixed pair used to be paid for by the message, which came
     * out about six characters wide and broke `sections/results.tex` across four lines.
     */
    const findings = page.locator('.rh-audit-finding');
    await expect(findings.first(), 'the seeded manuscript must produce findings').toBeVisible();
    const message = await page.evaluate(() => {
      const node = document.querySelector('.rh-audit-finding__message') as HTMLElement | null;
      if (node === null) throw new Error('no audit finding message');
      const probe = document.createElement('span');
      probe.style.display = 'inline-block';
      probe.style.inlineSize = '1ch';
      probe.style.position = 'absolute';
      probe.style.visibility = 'hidden';
      node.appendChild(probe);
      const oneCharacter = probe.getBoundingClientRect().width;
      probe.remove();
      return node.getBoundingClientRect().width / oneCharacter;
    });
    expect(
      message,
      `an audit finding's message ran ${message.toFixed(0)} characters at ${screen.label}`,
    ).toBeGreaterThanOrEqual(EDITOR_MIN_CHARACTERS);

    await page.screenshot({
      path: info.outputPath(`manuscript-${screen.label}-inspector.png`),
      fullPage: true,
    });

    // 3b. The file tree's entry file stays where it was: choosing a view never hides it.
    const entry = page.getByRole('treeitem', { name: /main\.tex/ }).first();
    await expect(entry, `the entry file must stay in view at ${screen.label}`).toBeInViewport();

    // Choosing a file brings the source back, which is the behaviour a tab must not cost.
    await entry.click();
    await expect(frame, `opening a file must show it at ${screen.label}`).toBeVisible();

    // 4. Wide enough to edit LaTeX in.
    const characters = await editorCharacters(page);
    expect(
      characters,
      `the editor ran ${characters.toFixed(0)} characters wide at ${screen.label}`,
    ).toBeGreaterThanOrEqual(EDITOR_MIN_CHARACTERS);

    // 5. No pane narrower than what it holds, and no sideways scroll on the page.
    const panes = await measurePanes(page);
    expect(
      panes.clipped,
      `panes clipped their content at ${screen.label} (workspace ${panes.workspace.toFixed(0)}px)`,
    ).toEqual([]);
    expect(
      panes.overflow,
      `the manuscript scrolls ${panes.overflow}px sideways at ${screen.label}`,
    ).toBeLessThanOrEqual(0);

    // 6. Nothing axe can name, at this width, in this theme.
    expect(await axeViolations(page), `the manuscript at ${screen.label}`).toEqual([]);

    await page.screenshot({
      path: info.outputPath(`manuscript-${screen.label}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}
