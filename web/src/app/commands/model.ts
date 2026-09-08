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
  /**
   * Which half of the palette it belongs to: somewhere to go, or something to do here.
   *
   * A page never sets it — everything a page registers is an action — and the shell sets
   * `GO_SECTION` on the rail's destinations. It is what lets the palette say that actions
   * exist before a researcher has typed anything into it.
   */
  section?: string;
  /** The single key that runs it. Held modifiers are never part of a page shortcut. */
  shortcut?: string;
  /**
   * The second key of a `g`-then-letter chord, for a command that goes somewhere.
   *
   * Destinations do not take single letters: those belong to the screen in front of the
   * researcher, where one of them accepts a candidate. `CHORD_LEAD` binds nothing on its
   * own, so nothing is lost to a lead key that is only ever half of a chord.
   */
  chord?: string;
  /** One line saying what pressing it does, for the help sheet. */
  hint?: string;
  run: () => void;
}

/** The key that opens a chord. Bound to nothing on its own, on any screen. */
export const CHORD_LEAD = 'g';

/**
 * How long a chord waits for its second key, in milliseconds.
 *
 * Long enough to be a chord and not a race; short enough that a lead key pressed by
 * accident cannot sit there and swallow a decision a minute later.
 */
export const CHORD_TIMEOUT = 1500;

/**
 * The letter that follows `g` for each of the rail's destinations, by navigation id.
 *
 * Every letter is one of the destination's own name, and no two are the same:
 *
 * | chord | destination   | why that letter          |
 * |-------|---------------|--------------------------|
 * | `g v` | Conversation  | con**v**ersation         |
 * | `g o` | Overview      | **O**verview             |
 * | `g r` | Review inbox  | **R**eview               |
 * | `g f` | Conflicts     | con**f**licts            |
 * | `g s` | Stale         | **S**tale                |
 * | `g c` | Corpus        | **C**orpus               |
 * | `g e` | Evidence      | **E**vidence             |
 * | `g l` | Claims        | c**l**aims               |
 * | `g q` | Questions     | **Q**uestions            |
 * | `g t` | Taxonomy      | **T**axonomy             |
 * | `g y` | Synthesis     | s**y**nthesis            |
 * | `g m` | Manuscript    | **M**anuscript           |
 *
 * They deliberately overlap with the single keys the review screen and the queue bind —
 * `r` refuses a candidate, `a` accepts one — and cannot collide with them: the letter of a
 * chord is only ever read while `g` has just been pressed, and it is consumed by the chord
 * whether or not it names a destination. A destination this table does not name keeps its
 * place in the palette and simply has no chord.
 */
export const DESTINATION_CHORDS: Readonly<Record<string, string>> = {
  conversation: 'v',
  overview: 'o',
  review: 'r',
  conflicts: 'f',
  stale: 's',
  corpus: 'c',
  evidence: 'e',
  claims: 'l',
  questions: 'q',
  taxonomy: 't',
  synthesis: 'y',
  manuscript: 'm',
};

/** The palette's two halves: where a researcher can go, and what this screen can do. */
export const GO_SECTION = 'Go to';
export const DO_SECTION = 'Actions';

/** The help sheet's heading for the chords. The palette's section says the same thing. */
export const CHORD_HEADING = 'Go to a screen';

export interface CommandSection {
  /** `GO_SECTION` or `DO_SECTION`; the palette prints it above the run. */
  name: string;
  /** Commands filed directly under the section, because their group repeats its name. */
  loose: Command[];
  /** The groups inside it, in the order they were first seen. */
  groups: [string, Command[]][];
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

/**
 * The commands in their two sections, each with the groups inside it.
 *
 * A command whose group names its own section — the ungrouped destinations, filed under
 * "Go to" because the rail gives them no heading of their own — is listed directly under
 * the section rather than under a heading that repeats it. Everything else keeps the
 * heading it named, so the rail's groups and a page's own survive the split.
 */
export function sectionCommands(commands: readonly Command[]): CommandSection[] {
  const sections: CommandSection[] = [];
  for (const command of commands) {
    const name = command.section ?? DO_SECTION;
    let section = sections.find((candidate) => candidate.name === name);
    if (!section) {
      section = { name, loose: [], groups: [] };
      sections.push(section);
    }
    if (command.group === name) {
      section.loose.push(command);
      continue;
    }
    const group = section.groups.find(([heading]) => heading === command.group);
    if (group) group[1].push(command);
    else section.groups.push([command.group, [command]]);
  }
  return sections;
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
 *
 * "On screen" is the load-bearing word. Below the shell's breakpoint the rail and the
 * inspector are drawers that stay in the document while they are closed, marked `hidden`,
 * so a mounted dialog is not necessarily one anybody can see — and a narrow window whose
 * keyboard silently stopped working would be the worst possible reading of this rule.
 */
export function foreignDialogOpen(root: Document | HTMLElement): boolean {
  const dialogs = root.querySelectorAll('[role="dialog"],[role="alertdialog"]');
  for (const dialog of Array.from(dialogs)) {
    if (dialog.hasAttribute('data-shell-overlay')) continue;
    if (dialog.closest('[hidden],[aria-hidden="true"]') !== null) continue;
    return true;
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
