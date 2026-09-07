/**
 * The shortcut layer, and the registry the palette and the help sheet read.
 *
 * The critique's finding was that review costs one page load per candidate: no shortcuts,
 * no palette, nothing a researcher who reviews all afternoon can lean on. This is the shell
 * half of the answer. It owns three things and no research logic at all:
 *
 * * a registry — a page registers the actions it already renders as controls, and they gain
 *   a keystroke, a palette entry and a line in the help sheet without being re-implemented;
 * * one document-level key listener, which refuses to fire while a researcher is typing or
 *   while a dialog it did not open is on screen;
 * * the two surfaces the keys summon: the palette on Ctrl/⌘+K and the help sheet on `?`.
 *
 * The navigation targets come from the shell rather than from this file, because the rail's
 * destinations are already derived once in `Layout` and a palette that listed a different
 * set would be a second navigation model.
 *
 * Mounted outside the shell — a view under test, a component rendered on its own — the
 * context falls back to a registry that accepts registrations and does nothing with them,
 * so a page never has to ask whether it has a shell.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Command } from './model';
import { foreignDialogOpen, isTypingTarget } from './model';
import { CommandPalette } from './CommandPalette';
import { ShortcutHelp } from './ShortcutHelp';
import './commands.css';

/**
 * A navigation destination the palette can take the researcher to.
 *
 * The shape is the rail's own `RailItem`, so the shell hands over the list it already
 * built rather than a second navigation model. `to` is optional there — an entry with no
 * route is a heading, not a destination — and one without it is simply not offered.
 */
export interface CommandDestination {
  id: string;
  label: string;
  to?: string | undefined;
}

export interface CommandsApi {
  /** Every command on offer right now: the shell's destinations, then the page's actions. */
  commands: Command[];
  /** Register a page's commands for as long as it is mounted; call the result to remove. */
  register: (commands: readonly Command[]) => () => void;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  helpOpen: boolean;
  setHelpOpen: (open: boolean) => void;
}

const NO_SHELL: CommandsApi = {
  commands: [],
  register: () => () => {},
  paletteOpen: false,
  setPaletteOpen: () => {},
  helpOpen: false,
  setHelpOpen: () => {},
};

const CommandsContext = createContext<CommandsApi>(NO_SHELL);

/** The palette and the help sheet are the only two keys the shell reserves for itself. */
export const SHELL_SHORTCUTS: { shortcut: string; label: string; hint: string }[] = [
  {
    shortcut: 'Mod+K',
    label: 'Command palette',
    hint: 'Go to any screen, or run what this one offers.',
  },
  { shortcut: '?', label: 'Keyboard shortcuts', hint: 'This list.' },
];

export interface CommandsProviderProps {
  /** The rail's destinations, so the palette and the navigation cannot disagree. */
  destinations?: readonly CommandDestination[];
  children: ReactNode;
}

interface Registration {
  key: number;
  commands: readonly Command[];
}

export function CommandsProvider({ destinations = [], children }: CommandsProviderProps) {
  const navigate = useNavigate();
  const [pages, setPages] = useState<readonly Registration[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const nextKey = useRef(0);

  const register = useCallback((commands: readonly Command[]) => {
    const key = (nextKey.current += 1);
    setPages((current) => [...current, { key, commands }]);
    return () => setPages((current) => current.filter((entry) => entry.key !== key));
  }, []);

  const commands = useMemo<Command[]>(() => {
    const goTo = destinations
      .filter((destination): destination is CommandDestination & { to: string } =>
        Boolean(destination.to),
      )
      .map<Command>((destination) => ({
        id: `go:${destination.id}`,
        label: destination.label,
        group: 'Go to',
        run: () => navigate(destination.to),
      }));
    return [...goTo, ...pages.flatMap((entry) => entry.commands)];
  }, [destinations, navigate, pages]);

  // The listener is installed once and reads the current commands through a ref: rebinding
  // it on every registration would drop a keystroke pressed while React was re-rendering.
  const state = useRef({ commands, paletteOpen, helpOpen });
  state.current = { commands, paletteOpen, helpOpen };

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.defaultPrevented || event.repeat) return;
      const { commands: current, paletteOpen: palette, helpOpen: help } = state.current;
      const shellOverlay = palette || help;
      if (!shellOverlay && foreignDialogOpen(document)) return;

      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setHelpOpen(false);
        setPaletteOpen(!palette);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      if (shellOverlay) return;

      if (event.key === '?') {
        event.preventDefault();
        setHelpOpen(true);
        return;
      }
      const command = current.find((entry) => entry.shortcut === event.key);
      if (!command) return;
      event.preventDefault();
      command.run();
    }

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const api = useMemo<CommandsApi>(
    () => ({ commands, register, paletteOpen, setPaletteOpen, helpOpen, setHelpOpen }),
    [commands, helpOpen, paletteOpen, register],
  );

  return (
    <CommandsContext.Provider value={api}>
      {children}
      <CommandPalette />
      <ShortcutHelp />
    </CommandsContext.Provider>
  );
}

/** The registry. Outside the shell this is the do-nothing one, never an exception. */
export function useCommands(): CommandsApi {
  return useContext(CommandsContext);
}

/**
 * Offer this page's commands for as long as it is mounted.
 *
 * `deps` works the way `useMemo`'s does, and for the same reason: the commands close over
 * the page's own state, so they are rebuilt when that state changes and re-registered only
 * then. A page that passes a fresh array every render would re-register forever.
 */
export function useRegisterCommands(factory: () => Command[], deps: unknown[]): void {
  const { register } = useCommands();
  const commands = useMemo(factory, deps);
  useEffect(() => register(commands), [commands, register]);
}
