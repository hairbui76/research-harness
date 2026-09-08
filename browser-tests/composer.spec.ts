/**
 * Where an unpublished message goes, in a real browser, against the real daemon.
 *
 * The egress disclosure is a dialog a researcher answers once per session. This test is
 * about everything after that: a project is created, a session is opened through the real
 * UI, and the composer is asked — at both widths the suite runs — to keep saying where the
 * next message would go and whether it leaves the machine.
 *
 * The runtimes are whatever is actually installed on this workstation, so nothing here
 * hard-codes Codex or Claude Code. What the daemon's scan offers is read out of the picker
 * and asserted against the line; a workstation with no routable runtime and a project with
 * no `providers:` table is a real state too, and it is asserted as the honest silence it is
 * rather than skipped.
 */
import { expect, test } from '@playwright/test';
import { axeViolations } from './axe';

/** The 768px project; the rail is a drawer there and has to be opened to be used. */
const NARROW = 'narrow-light';

/** `Sends to <runtime> · <model> — leaves this machine for <host>`. */
const EXTERNAL_RUNTIME = /^Sends to (.+) · (.+) — leaves this machine for (\S+)$/;

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => {
    localStorage.setItem('research-harness:design:appearance', JSON.stringify({ theme }));
  }, info.project.name.endsWith('light') ? 'light' : 'dark');
});

test('the composer keeps saying where an unpublished message goes', async ({
  page,
  request,
}, info) => {
  // Creating a project, scanning the workstation's CLI runtimes and two axe passes is more
  // than one default timeout.
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce, parent } = await bootstrap.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page
    .getByLabel('Project name', { exact: true })
    .fill(`Composer study ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await page.waitForURL(/\/projects\/[^/?#]+/);

  // A session, opened the way a researcher opens one. The default visibility is `project`,
  // which is the kind of session a CLI runtime may be bound to at all.
  const narrow = info.project.name === NARROW;
  if (narrow) await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  // Scoped to the rail: with no session open the composer offers the same control, by the
  // same name, in the same window — which is the point of the front door and the reason
  // this locator has to say which of the two it means.
  await page
    .getByRole('navigation', { name: 'Project navigation' })
    .getByRole('button', { name: 'New session', exact: true })
    .click();
  const dialog = page.getByRole('dialog', { name: 'New session' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Visibility' })).toHaveValue('project');
  await dialog.getByRole('button', { name: 'Create session', exact: true }).click();
  await expect(dialog).toBeHidden();
  if (narrow) {
    const close = page.getByRole('button', { name: 'Close project navigation' });
    if (await close.isVisible()) await close.click();
  }
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeVisible();

  const destination = page.locator('.rh-composer__destination');
  const picker = page.getByRole('button', { name: /^Model:/ });

  /**
   * The composer never scrolls sideways, and at 768px neither does the page.
   *
   * The page-wide check is asserted at the narrow width only: at 1440px the conversation
   * route already overflows on the inspector's six tabs, which is the critique's own P2 and
   * is being fixed elsewhere. Failing here for that would say nothing about this line.
   */
  const fits = async (where: string): Promise<void> => {
    const composer = await page.evaluate(() => {
      const node = document.querySelector('.rh-composer');
      return node === null ? true : node.scrollWidth <= node.clientWidth;
    });
    expect(composer, `${where}: the composer must not overflow horizontally`).toBeTruthy();
    // A trigger that names a model and says nothing about egress is the one regression the
    // removal of the EXTERNAL/LOCAL tag must not cause. Once the scan has settled, the two
    // stand or fall together: no picker, or a picker with the line beside it.
    if ((await picker.count()) > 0) {
      await expect(
        destination,
        `${where}: a rendered model trigger states no destination`,
      ).toHaveCount(1);
    }
    if (!narrow) return;
    const whole = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(whole, `${where}: the page must not overflow horizontally at 768px`).toBeTruthy();
  };

  // The picker arrives with the daemon's scan of this workstation's CLI runtimes, which is
  // a real process launch per runtime; a scan that never produces one is the no-runtime
  // state, and it is asserted rather than skipped.
  const offers = await picker
    .waitFor({ state: 'visible', timeout: 60_000 })
    .then(() => true)
    .catch(() => false);

  if (!offers) {
    // No `providers:` table and no routable runtime: this cockpit has been told nothing
    // about where a message would go, and it says nothing rather than guessing.
    await expect(destination).toHaveCount(0);
    await fits('with no destination to state');
    await page.screenshot({ path: info.outputPath('composer-no-runtime.png'), fullPage: true });
    expect(errors).toEqual([]);
    return;
  }

  // A project created a moment ago has no configured entries, so the unbound state is the
  // picker's own project-default row, stated in the picker's own words.
  await expect(destination).toHaveText('Sends to Project default — leaves this machine');
  // Described, not announced: the line is part of the message box, never a live region.
  const described = await page
    .getByRole('textbox', { name: 'Message' })
    .getAttribute('aria-describedby');
  const lineId = await destination.getAttribute('id');
  expect((described ?? '').split(' ')).toContain(lineId);
  await expect(destination).not.toHaveAttribute('aria-live', /.*/);
  await fits('with no binding');
  await page.screenshot({ path: info.outputPath('composer-unbound.png'), fullPage: true });

  /** Every runtime model the daemon's scan says this workstation can actually route to. */
  const routable = async (): Promise<{ id: string; runtime: string; model: string }[]> => {
    const menu = page.getByRole('menu', { name: 'Model' });
    const ids = await menu
      .locator('[role="menuitem"][data-model^="runtime:"]:not([aria-disabled="true"])')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-model') ?? ''));
    return ids.flatMap((id) => {
      const rest = id.slice('runtime:'.length);
      const at = rest.indexOf(':');
      return at <= 0 ? [] : [{ id, runtime: rest.slice(0, at), model: rest.slice(at + 1) }];
    });
  };

  await picker.click();
  await expect(page.getByRole('menu', { name: 'Model' })).toBeVisible();
  const offered = await routable();
  if (offered.length === 0) {
    // A workstation with no runtime installed, logged in and provably bounded. The picker
    // is there for the entries; the line still states the project default and nothing more.
    await page.keyboard.press('Escape');
    await expect(destination).toHaveText('Sends to Project default — leaves this machine');
    await page.screenshot({ path: info.outputPath('composer-no-runtime.png'), fullPage: true });
    expect(errors).toEqual([]);
    return;
  }

  /** Bind the session to one runtime model, answering the disclosure the first time only. */
  const bind = async (
    target: { id: string; runtime: string; model: string },
    first: boolean,
  ): Promise<string> => {
    // What the line says now, so the assertion after the pick waits for the record to come
    // back rather than reading the sentence that is still on screen.
    const before = (await destination.textContent()) ?? '';
    const menu = page.getByRole('menu', { name: 'Model' });
    const item = menu.locator(`[role="menuitem"][data-model="${target.id}"]`);
    // The runtime's own heading in the picker, to check the line names the same runtime.
    // `textContent`, not `innerText`: the heading is rendered uppercase by the menu's own
    // stylesheet, and the runtime's name is the one the scan gave.
    const heading = await item
      .locator('xpath=ancestor::*[@role="group"][1]')
      .locator('.rh-menu__group-label')
      .textContent();
    await item.click();
    const disclosure = page.getByRole('alertdialog');
    if (first) {
      await expect(disclosure).toBeVisible();
      await disclosure.getByRole('button', { name: 'Use this runtime' }).click();
    } else {
      // Asked once per session — which is precisely why the line has to stay.
      await expect(disclosure).toHaveCount(0);
    }
    await expect(destination).not.toHaveText(before);
    return heading ?? '';
  };

  const first = offered[0]!;
  const heading = await bind(first, true);

  // The bound runtime, its model and the host the scan says it reaches, all in the line.
  await expect(destination).toHaveText(EXTERNAL_RUNTIME);
  const bound = EXTERNAL_RUNTIME.exec((await destination.textContent()) ?? '');
  expect(bound, 'the destination line must name a runtime, a model and a host').not.toBeNull();
  expect(bound![2]).toBe(first.model);
  // The picker heading is the runtime's name and version; the line is the name alone.
  expect(heading.startsWith(bound![1]!)).toBeTruthy();

  // The whole page, not just the composer. This run used to be scoped to `.rh-composer`
  // because the conversation route's dark theme failed `color-contrast` on the session
  // list's active row; 2H fixed that at the token, so the scope comes off. A session is
  // open here, which is the only state where that row exists — so this is the route-wide
  // run that keeps it fixed.
  expect(await axeViolations(page), 'the conversation route with a bound session').toEqual([]);
  await fits('bound to a runtime');
  await page.screenshot({ path: info.outputPath('composer-bound.png'), fullPage: true });

  // A second runtime, when this workstation has one, changes the line and nothing else.
  const other = offered.find((entry) => entry.runtime !== first.runtime);
  let current = first;
  if (other !== undefined) {
    current = other;
    await picker.click();
    await expect(page.getByRole('menu', { name: 'Model' })).toBeVisible();
    const otherHeading = await bind(other, false);
    await expect(destination).toHaveText(EXTERNAL_RUNTIME);
    const rebound = EXTERNAL_RUNTIME.exec((await destination.textContent()) ?? '');
    expect(rebound).not.toBeNull();
    expect(rebound![2]).toBe(other.model);
    expect(rebound![1]).not.toBe(bound![1]);
    expect(otherHeading.startsWith(rebound![1]!)).toBeTruthy();
    await fits('bound to a second runtime');
    await page.screenshot({ path: info.outputPath('composer-rebound.png'), fullPage: true });
  }

  // The line is an addition to the surfaces that already state the destination, not a
  // replacement: the rail keeps the record's binding in the format every surface uses.
  if (narrow) await page.getByRole('button', { name: 'Project navigation', exact: true }).click();
  await expect(page.locator('.rh-session-list__binding').first()).toHaveText(
    `session:${current.runtime}/${current.model}`,
  );

  expect(errors).toEqual([]);
});

/**
 * The front door, in a real browser, at both widths the suite runs.
 *
 * A project created a moment ago has no session, and that is the first screen a newcomer
 * to the conversation route meets. It used to be a message box with an accent Send,
 * disabled, and a sentence six hundred pixels above it naming a control called something
 * else. The daemon has no create-on-send — `session.send` takes a session id and
 * `SendService._prepare` reads that record before anything happens — so the way in is one
 * control, in the rail's words, in the slot the message box will occupy.
 */
test('the conversation opens from one control, in the rail’s own words', async ({
  page,
  request,
}, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  const bootstrap = await request.get('/__test__/bootstrap');
  expect(bootstrap.ok()).toBeTruthy();
  const { nonce, parent } = await bootstrap.json();
  await page.goto(`/?bootstrap=${encodeURIComponent(nonce)}`);
  await expect(page.getByRole('heading', { name: 'Your research projects' })).toBeVisible();

  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(`Entrance study ${info.project.name}`);
  await page.getByRole('button', { name: 'Choose parent folder' }).click();
  await page.getByLabel('Parent folder path').fill(parent);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/projects/create') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  expect((await created).ok()).toBeTruthy();
  await page.waitForURL(/\/projects\/[^/?#]+/);

  // Nothing to type into, and no Send pretending it could be pressed.
  await expect(page.getByText('No session open')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Message' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send' })).toHaveCount(0);

  // The transcript names the control by the name the control actually wears.
  await expect(
    page.getByText('Choose New session below to ask a question against this project.'),
  ).toBeVisible();
  const entrance = page.locator('.rh-web-entrance').getByRole('button', { name: 'New session' });
  await expect(entrance).toBeVisible();
  await page.screenshot({ path: info.outputPath('composer-entrance.png'), fullPage: true });

  // One control, the same question the rail asks, and the caret lands in the box it opened.
  await entrance.click();
  const dialog = page.getByRole('dialog', { name: 'New session' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Visibility' })).toHaveValue('project');
  await dialog.getByRole('button', { name: 'Create session', exact: true }).click();
  await expect(dialog).toBeHidden();
  const box = page.getByRole('textbox', { name: 'Message' });
  await expect(box).toBeVisible();
  await expect(box).toBeFocused();

  expect(await axeViolations(page), 'the conversation route with no session and with one').toEqual(
    [],
  );

  /*
   * The chrome under the box, measured rather than assumed.
   *
   * Four rows sat here at 768: the toolbar, the keyboard hint, the destination and the
   * index state. The destination keeps a line of its own; the two standing facts share one
   * once the index state has been read, which is what the reload below is for.
   */
  await page.reload();
  // Enabled, not merely present: a box that is still waiting for its session record renders
  // disabled with its own reason, and measuring the footer mid-boot measures nothing.
  await expect(page.getByRole('textbox', { name: 'Message' })).toBeEnabled({ timeout: 30_000 });
  const note = page.locator('.rh-composer__note');
  if ((await note.count()) > 0) {
    const rows = await page.evaluate(() => {
      const hint = document.querySelector('.rh-composer__hints .rh-composer__hint');
      const folded = document.querySelector('.rh-composer__hints .rh-composer__note');
      const standing = document.querySelector('.rh-composer__footer > .rh-composer__note');
      return {
        folded: folded !== null,
        standing: standing !== null,
        sameRow:
          hint !== null && folded !== null
            ? Math.abs(hint.getBoundingClientRect().top - folded.getBoundingClientRect().top) < 2
            : false,
      };
    });
    expect(rows.standing, 'a read index note must not keep a row of its own').toBeFalsy();
    expect(rows.folded, 'a read index note folds into the composer footer').toBeTruthy();
    expect(rows.sameRow, 'the keyboard hint and the read index note share one line').toBeTruthy();
  }
  await page.screenshot({ path: info.outputPath('composer-footer.png'), fullPage: true });

  expect(errors).toEqual([]);
});
