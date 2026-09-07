/** The shortcut layer, its registry, and the two surfaces the keys summon. */
export { CommandsProvider, SHELL_SHORTCUTS, useCommands, useRegisterCommands } from './CommandsProvider';
export type { CommandDestination, CommandsApi, CommandsProviderProps } from './CommandsProvider';
export { CommandPalette } from './CommandPalette';
export { ShortcutHelp } from './ShortcutHelp';
export {
  foreignDialogOpen,
  groupCommands,
  isTypingTarget,
  matchCommands,
  modifierLabel,
  shortcutLabel,
} from './model';
export type { Command } from './model';
