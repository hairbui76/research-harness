export { ThemeProvider, useTheme, useOptionalTheme, THEME_STORAGE_KEY } from './ThemeProvider';
export type { ThemeContextValue, ThemeProviderProps } from './ThemeProvider';
export { AppShell } from './AppShell';
export type { AppShellProps } from './AppShell';
export { ProjectRail } from './ProjectRail';
export type { ProjectRailProps } from './ProjectRail';
export { ConversationWorkspace } from './ConversationWorkspace';
export type { ConversationWorkspaceProps } from './ConversationWorkspace';
export { ResearchInspector } from './ResearchInspector';
export type { ResearchInspectorProps } from './ResearchInspector';
export { FullPageWorkspace } from './FullPageWorkspace';
export type { FullPageWorkspaceProps } from './FullPageWorkspace';
export { ManuscriptWorkspace } from './ManuscriptWorkspace';
export type { ManuscriptWorkspaceProps, ManuscriptView } from './ManuscriptWorkspace';

export {
  INSPECTOR_TABS,
  INSPECTOR_TAB_META,
  PROJECT_AVAILABILITY_META,
  PROVIDER_STATE_META,
  SELECTION_KIND_META,
  mergePaneSizes,
  resolvePaneSizes,
} from './models';
export type {
  InspectorRef,
  InspectorSelection,
  InspectorTab,
  PaneSizes,
  ProjectAction,
  ProjectAvailability,
  ProjectModel,
  ProviderStatus,
  RailItem,
} from './models';
