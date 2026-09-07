/**
 * What the keyboard can do here, on `?` or from the palette.
 *
 * The critique found no help affordance anywhere in the cockpit. This is the smallest
 * honest one: it lists the keys that are actually bound right now — the shell's two, the
 * chords that go to a screen, then whatever the open page registered — so it cannot promise
 * a shortcut the page does not offer, and a screen with no shortcuts of its own says so.
 *
 * "Actually bound" includes the switch at the top. Every page shortcut is a single
 * character pressed with no modifier, and a researcher who dictates or uses a switch device
 * has to be able to turn those off (WCAG 2.2 2.1.4). With them off this sheet stops listing
 * them, because listing a key that would not fire is the same lie in the other direction.
 */
import { Dialog, DialogBody, DialogHeader, Switch } from '@research-harness/design';
import { SHELL_SHORTCUTS, useCommands } from './CommandsProvider';
import { CHORD_HEADING, GO_SECTION, groupCommands, shortcutLabel } from './model';
import { ShortcutKeys } from './ShortcutKeys';

export function ShortcutHelp() {
  const { commands, helpOpen, setHelpOpen, singleKeys, setSingleKeys } = useCommands();
  if (!helpOpen) return null;

  const bound = commands.filter((command) => command.shortcut !== undefined);
  const groups = singleKeys ? groupCommands(bound) : [];
  // The chords, under one heading of their own: they all do the same kind of thing, and
  // the rail's three groups are a shape for browsing rather than for learning eleven keys.
  const going = singleKeys ? commands.filter((command) => command.chord !== undefined) : [];
  // Only the chord survives the switch being off, so only the chord is listed.
  const anywhere = SHELL_SHORTCUTS.filter(
    (entry) => singleKeys || entry.shortcut.startsWith('Mod+'),
  );

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
            <Switch
              label="Single-key shortcuts"
              checked={singleKeys}
              onCheckedChange={setSingleKeys}
            />
            <p className="rh-text-secondary rh-web-shortcuts__note">
              A single letter runs the action it stands for the moment it is pressed outside a
              text box, and one of them accepts a candidate. Turn it off if you dictate or use
              a switch device, where a stray character would decide something. {' '}
              {shortcutLabel('Mod+K')} still opens the palette, and everything the keys reach
              is on it.
            </p>
          </section>

          <section className="rh-web-shortcuts__group">
            <h3 className="rh-text-h4">Anywhere</h3>
            <dl className="rh-web-shortcuts__list">
              {anywhere.map((entry) => (
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

          {going.length > 0 ? (
            <section className="rh-web-shortcuts__group">
              <h3 className="rh-text-h4">{CHORD_HEADING}</h3>
              <p className="rh-text-secondary rh-web-shortcuts__note">
                Two keys: <kbd className="rh-web-kbd">g</kbd>, then the letter. The letter is
                only read while the chord is open, so it never collides with the single key
                the screen in front of you binds.
              </p>
              <dl className="rh-web-shortcuts__list">
                {going.map((command) => (
                  <div key={command.id} className="rh-web-shortcuts__row">
                    <dt>
                      <ShortcutKeys command={command} singleKeys={singleKeys} />
                    </dt>
                    <dd>
                      <span className="rh-web-shortcuts__label">{command.label}</span>
                      {/* The rail's heading for it, and nothing where the rail gives it
                          none: "Conversation Go to" is not a sentence anybody reads. */}
                      {command.group === GO_SECTION ? null : (
                        <> <span className="rh-text-secondary">{command.group}</span></>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          {groups.map(([group, items]) => (
            <section key={group} className="rh-web-shortcuts__group">
              <h3 className="rh-text-h4">{group}</h3>
              <dl className="rh-web-shortcuts__list">
                {items.map((command) => (
                  <div key={command.id} className="rh-web-shortcuts__row">
                    <dt>
                      <ShortcutKeys command={command} singleKeys={singleKeys} />
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

          {singleKeys && bound.length === 0 ? (
            <p className="rh-text-secondary">
              This screen binds no keys of its own. The palette reaches every other one.
            </p>
          ) : null}
          {singleKeys ? null : (
            <p className="rh-text-secondary">
              The single keys are off, so nothing below the chord is bound. The palette runs
              every one of them, and this screen's own controls are unchanged.
            </p>
          )}
        </div>
      </DialogBody>
    </Dialog>
  );
}
