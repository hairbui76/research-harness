/**
 * What the keyboard can do here, on `?`.
 *
 * The critique found no help affordance anywhere in the cockpit. This is the smallest
 * honest one: it lists the keys that are actually bound right now — the shell's two, then
 * whatever the open page registered — so it cannot promise a shortcut the page does not
 * offer, and a screen with no shortcuts of its own says so.
 */
import { Dialog, DialogBody, DialogHeader } from '@research-harness/design';
import { SHELL_SHORTCUTS, useCommands } from './CommandsProvider';
import { groupCommands, shortcutLabel } from './model';

export function ShortcutHelp() {
  const { commands, helpOpen, setHelpOpen } = useCommands();
  if (!helpOpen) return null;

  const bound = commands.filter((command) => command.shortcut !== undefined);
  const groups = groupCommands(bound);

  return (
    <Dialog
      open
      onOpenChange={setHelpOpen}
      size="md"
      className="rh-web-shortcuts"
      data-shell-overlay=""
    >
      <DialogHeader>Keyboard shortcuts</DialogHeader>
      <DialogBody>
        <div className="rh-web-stack">
          <section className="rh-web-shortcuts__group">
            <h3 className="rh-text-label">Anywhere</h3>
            <dl className="rh-web-shortcuts__list">
              {SHELL_SHORTCUTS.map((entry) => (
                <div key={entry.shortcut} className="rh-web-shortcuts__row">
                  <dt>
                    <kbd className="rh-web-kbd">{shortcutLabel(entry.shortcut)}</kbd>
                  </dt>
                  <dd>
                    <span className="rh-web-shortcuts__label">{entry.label}</span>{' '}
                    <span className="rh-text-secondary">{entry.hint}</span>
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          {groups.map(([group, items]) => (
            <section key={group} className="rh-web-shortcuts__group">
              <h3 className="rh-text-label">{group}</h3>
              <dl className="rh-web-shortcuts__list">
                {items.map((command) => (
                  <div key={command.id} className="rh-web-shortcuts__row">
                    <dt>
                      <kbd className="rh-web-kbd">{shortcutLabel(command.shortcut ?? '')}</kbd>
                    </dt>
                    <dd>
                      <span className="rh-web-shortcuts__label">{command.label}</span>
                      {command.hint ? (
                        <> <span className="rh-text-secondary">{command.hint}</span></>
                      ) : null}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}

          {bound.length === 0 ? (
            <p className="rh-text-secondary">
              This screen binds no keys of its own. The palette reaches every other one.
            </p>
          ) : null}
        </div>
      </DialogBody>
    </Dialog>
  );
}
