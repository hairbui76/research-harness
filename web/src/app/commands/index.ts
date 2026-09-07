/** The shortcut layer, its registry, and the two surfaces the keys summon. */
export {
  CommandsProvider,
  SHELL_SHORTCUTS,
  SINGLE_KEY_SHORTCUTS,
  readSingleKeys,
  useCommands,
  useRegisterCommands,
} from './CommandsProvider';
export type { CommandDestination, CommandsApi, CommandsProviderProps } from './CommandsProvider';
export { CommandPalette } from './CommandPalette';
export { ShortcutHelp } from './ShortcutHelp';
export { ShortcutKeys } from './ShortcutKeys';
export {
  CHORD_HEADING,
  CHORD_LEAD,
  CHORD_TIMEOUT,
  DESTINATION_CHORDS,
  DO_SECTION,
  GO_SECTION,
  foreignDialogOpen,
  groupCommands,
  isTypingTarget,
  matchCommands,
  modifierLabel,
  sectionCommands,
  shortcutLabel,
} from './model';
export type { Command, CommandSection } from './model';
