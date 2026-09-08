/**
 * The palette: every screen and every action this one offers, one keystroke away.
 *
 * It is a `Dialog` because it is an interruption the researcher summoned — the rest of the
 * cockpit should be inert while it is up, and focus belongs inside it until it is answered
 * or dismissed. The list is the ARIA combobox pattern: focus stays in the text box, the
 * active option is named by `aria-activedescendant`, and Enter runs it, so a screen reader
 * hears the option change while the caret stays where the researcher is typing.
 *
 * The palette runs the page's own handler. It cannot do anything a control on the screen
 * behind it could not.
 *
 * It reads in two sections — where a researcher can go, and what this screen can do — with
 * the rail's own headings inside the first. The critique found a power user opening it and
 * seeing a list of destinations with nothing saying that actions were on it at all; the
 * second section is on screen before anything is typed, and on a page that registers no
 * actions it still holds the shell's own.
 *
 * The dialog is named for what it is. It used to be titled "Go to, or do", which described
 * the two sections rather than the object, and the sentence under the search box already
 * counts both of them — so the title spent the one line a first-timer reads on something
 * said twice, and never on the name of the thing that had appeared over their work.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Dialog, DialogBody, DialogHeader, Input, useId } from '@research-harness/design';
import { useCommands } from './CommandsProvider';
import { DO_SECTION, GO_SECTION, matchCommands, sectionCommands } from './model';
import type { CommandSection } from './model';
import { ShortcutKeys } from './ShortcutKeys';

/** How many commands a section holds, in the words its own name is read with. */
function counted(section: CommandSection | undefined, singular: string): string {
  const count = section === undefined ? 0 : section.loose.length + section.groups.reduce(
    (total, [, items]) => total + items.length,
    0,
  );
  if (count === 0) return `no ${singular}s`;
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

export function CommandPalette() {
  const { commands, paletteOpen, setPaletteOpen, singleKeys } = useCommands();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const baseId = useId(undefined, 'rh-web-palette');
  const listId = `${baseId}-commands`;
  const inputRef = useRef<HTMLInputElement | null>(null);

  const matches = useMemo(() => matchCommands(commands, query), [commands, query]);
  const sections = useMemo(() => sectionCommands(matches), [matches]);

  // A palette opened again starts from the top with an empty query: it is a way in, not a
  // place that remembers what was asked last time.
  useEffect(() => {
    if (paletteOpen) {
      setQuery('');
      setActive(0);
    }
  }, [paletteOpen]);

  if (!paletteOpen) return null;

  const optionId = (command: { id: string }): string =>
    `${baseId}-${command.id.replace(/[^A-Za-z0-9_-]/g, '-')}`;

  const option = (command: (typeof matches)[number]) => {
    const index = matches.indexOf(command);
    return (
      <div
        key={command.id}
        id={optionId(command)}
        role="option"
        aria-selected={index === active}
        data-active={index === active ? '' : undefined}
        className="rh-web-palette__option"
        // `mousemove`, not `mouseenter`: the palette is summoned by keyboard and appears
        // under wherever the pointer was last left, and an option that takes the selection
        // without the mouse having moved would let Enter run whatever the cursor happens to
        // be resting on.
        onMouseMove={() => setActive(index)}
        // Keep the caret and the active option where they are; the click runs it.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => run(index)}
      >
        <span>{command.label}</span>
        <ShortcutKeys command={command} singleKeys={singleKeys} />
      </div>
    );
  };

  const run = (index: number): void => {
    const command = matches[index];
    if (!command) return;
    setPaletteOpen(false);
    command.run();
  };

  const move = (delta: number): void => {
    if (matches.length === 0) return;
    setActive((current) => (current + delta + matches.length) % matches.length);
  };

  return (
    <Dialog
      open
      onOpenChange={setPaletteOpen}
      size="md"
      className="rh-web-palette"
      data-shell-overlay=""
      initialFocusRef={inputRef}
    >
      <DialogHeader>Command palette</DialogHeader>
      <DialogBody className="rh-web-palette__body">
        <Input
          ref={inputRef}
          label="Search screens and actions"
          hideLabel
          placeholder="Search screens and actions"
          iconStart="search"
          autoComplete="off"
          role="combobox"
          aria-expanded
          aria-controls={listId}
          aria-autocomplete="list"
          {...(matches[active] ? { 'aria-activedescendant': optionId(matches[active]) } : {})}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              move(1);
            } else if (event.key === 'ArrowUp') {
              event.preventDefault();
              move(-1);
            } else if (event.key === 'Enter') {
              event.preventDefault();
              run(active);
            }
          }}
        />

        {/*
          One line saying what is in the list, before any of it is scrolled to. Eleven
          destinations fill the list on their own, so the actions section is below the fold
          on a tall rail — and the whole point of the section is that a power user learns
          this screen has actions without typing anything (critique H7, Alex).
        */}
        {matches.length > 0 ? (
          <p className="rh-web-palette__summary">
            {counted(sections.find((section) => section.name === GO_SECTION), 'screen')} to go
            to, and {counted(sections.find((section) => section.name === DO_SECTION), 'action')}{' '}
            on this screen.
          </p>
        ) : null}

        <div id={listId} role="listbox" aria-label="Screens and actions" className="rh-web-palette__list">
          {sections.map((section) => (
            <div
              key={section.name}
              role="group"
              aria-label={section.name}
              className="rh-web-palette__section"
            >
              <p className="rh-web-palette__section-heading">{section.name}</p>
              {section.loose.map(option)}
              {section.groups.map(([group, items]) => (
                <div key={group} role="group" aria-label={group} className="rh-web-palette__group">
                  <p className="rh-web-palette__heading">{group}</p>
                  {items.map(option)}
                </div>
              ))}
            </div>
          ))}
        </div>

        {matches.length === 0 ? (
          <p className="rh-web-palette__empty">
            Nothing here is called “{query}”. Clear the search to see every screen.
          </p>
        ) : null}
      </DialogBody>
    </Dialog>
  );
}
