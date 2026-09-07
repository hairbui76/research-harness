/**
 * The keys a command is bound to, printed the same way wherever they are printed.
 *
 * One `kbd` per key a researcher actually presses: a chord is two of them, in the order
 * they are pressed, because "g r" as one box would read as a key that does not exist. The
 * palette prints them beside the option and the help sheet in its own column, and both go
 * through here so a shortcut cannot be shown one way in one place and another way in the
 * other.
 *
 * Nothing is printed when the single keys are off. A key that would not fire, shown as if
 * it would, is the same lie the help sheet already refuses to tell.
 */
import { CHORD_LEAD, shortcutLabel } from './model';
import type { Command } from './model';

export interface ShortcutKeysProps {
  command: Pick<Command, 'shortcut' | 'chord'>;
  /** Whether the bare-character layer is on. A chord is bare characters too. */
  singleKeys: boolean;
}

export function ShortcutKeys({ command, singleKeys }: ShortcutKeysProps) {
  if (!singleKeys) return null;
  if (command.chord) {
    return (
      <span className="rh-web-kbd-chord">
        <kbd className="rh-web-kbd">{CHORD_LEAD}</kbd>
        <kbd className="rh-web-kbd">{command.chord}</kbd>
      </span>
    );
  }
  if (command.shortcut === undefined) return null;
  return <kbd className="rh-web-kbd">{shortcutLabel(command.shortcut)}</kbd>;
}
