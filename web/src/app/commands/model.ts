/**
 * What a command is, and the two rules the shortcut layer is built on.
 *
 * A command is one thing a researcher can do from the keyboard: a page registers the
 * actions it already offers as buttons, and the shell lends them a palette, a shortcut and
 * a line in the help sheet. Nothing here performs anything — `run` is the page's own
 * handler, so a shortcut and the button beside it can never drift apart.
 */

export interface Command {
  /** Stable identity. Also the palette option's DOM id, so it must survive a re-render. */
  id: string;
  /** What the command is called, in the same words as the control it stands for. */
  label: string;
  /** The heading it is listed under, in the palette and in the help sheet. */
  group: string;
  /** The single key that runs it. Held modifiers are never part of a page shortcut. */
  shortcut?: string;
  /** One line saying what pressing it does, for the help sheet. */
  hint?: string;
  run: () => void;
}

/**
 * The commands a query selects, in the order they were registered.
 *
 * Every whitespace-separated term must appear somewhere in the command's label, its group
 * or its hint, so `rev inb` finds "Review inbox" without a fuzzy matcher inventing ranks.
 * The order is never changed: the shell registered navigation first and the page second,
 * and that is the order a researcher reads.
 */
export function matchCommands(commands: readonly Command[], query: string): Command[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [...commands];
  return commands.filter((command) => {
    const haystack = `${command.label} ${command.group} ${command.hint ?? ''}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}

/** The commands grouped under their headings, keeping the registration order of both. */
export function groupCommands(commands: readonly Command[]): [string, Command[]][] {
  const groups: [string, Command[]][] = [];
  for (const command of commands) {
    const last = groups.find(([name]) => name === command.group);
    if (last) last[1].push(command);
    else groups.push([command.group, [command]]);
  }
  return groups;
}

/**
 * Whether this keystroke is being typed rather than pressed.
 *
 * A researcher writing the sentence a rejection is recorded with is not asking to reject
 * something else, so the shortcut layer stays out of every text control — including a
 * contenteditable surface, which reports no tag name of its own.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (target === null || !(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

/**
 * Whether a dialog the shell does not own is on screen.
 *
 * The palette and the help sheet are summoned by the shortcut layer and marked as its own;
 * any other dialog — editing the proposed evidence, settings, a project lifecycle question —
 * is a task the researcher is inside, and a single letter must not reach past it.
 */
export function foreignDialogOpen(root: Document | HTMLElement): boolean {
  const dialogs = root.querySelectorAll('[role="dialog"],[role="alertdialog"]');
  for (const dialog of Array.from(dialogs)) {
    if (!dialog.hasAttribute('data-shell-overlay')) return true;
  }
  return false;
}

/** `Ctrl` or the Command key, whichever this machine's keyboard actually has. */
export function modifierLabel(): string {
  const platform =
    typeof navigator === 'undefined' ? '' : (navigator.platform ?? navigator.userAgent ?? '');
  return /mac|iphone|ipad/i.test(platform) ? '⌘' : 'Ctrl';
}

/** A shortcut as the help sheet and the palette print it. */
export function shortcutLabel(shortcut: string): string {
  return shortcut.replace(/^Mod\+/, `${modifierLabel()} `);
}
