/**
 * @research-harness/design — the Research Harness Design System.
 *
 * Presentation only. Nothing in this package fetches, calls the daemon, mutates research
 * state, or knows a research rule; components take typed view models and callbacks.
 *
 * Consumers need two imports:
 *
 *   import { Button } from '@research-harness/design';
 *   import '@research-harness/design/styles.css';
 */

/** The themes the package ships. Dark is the default and needs no attribute. */
export const THEMES = ['dark', 'light'] as const;
export type Theme = (typeof THEMES)[number];

/** Density modes. Set `data-density` on any element; it cascades to its subtree. */
export const DENSITIES = ['comfortable', 'compact'] as const;
export type Density = (typeof DENSITIES)[number];

// Shared helpers
export { cx } from './utils/cx';
export type { ClassValue } from './utils/cx';
export { useControllable } from './utils/useControllable';
export type { ControllableOptions } from './utils/useControllable';
export { joinIds, useAutoId, useFieldIds } from './utils/ids';
export type { FieldIds } from './utils/ids';

// Core primitives
export { Icon, ICON_SIZES, ICON_NAMES, icons } from './primitives/Icon';
export type { IconName, IconProps, IconSize } from './primitives/Icon';
export { Button } from './primitives/Button';
export type { ButtonProps, ButtonSize, ButtonVariant } from './primitives/Button';
export { IconButton } from './primitives/IconButton';
export type { IconButtonProps, IconButtonSize } from './primitives/IconButton';
export { Badge, STATUS_META, STATUS_NAMES } from './primitives/Badge';
export type { BadgeProps, BadgeSize, BadgeTone, StatusMeta, StatusName } from './primitives/Badge';
export { Tag } from './primitives/Tag';
export type { TagProps, TagSize } from './primitives/Tag';
export { Card } from './primitives/Card';
export type { CardElement, CardPadding, CardProps, CardSurface } from './primitives/Card';

// Form primitives
export { Input } from './primitives/Input';
export type { InputProps, InputSize } from './primitives/Input';
export { Textarea } from './primitives/Textarea';
export type { TextareaProps } from './primitives/Textarea';
export { Select } from './primitives/Select';
export type { SelectProps, SelectSize } from './primitives/Select';
export { Checkbox } from './primitives/Checkbox';
export type { CheckboxProps } from './primitives/Checkbox';
export { Radio, RadioGroup } from './primitives/Radio';
export type { RadioGroupProps, RadioProps } from './primitives/Radio';
export { Switch } from './primitives/Switch';
export type { SwitchProps } from './primitives/Switch';

// overlay, navigation, and layout primitives (DS1b) are exported below

// Overlay, navigation, and layout primitives
export { Tabs, TabList, Tab, TabPanel } from './primitives/Tabs';
export type {
  TabsProps,
  TabListProps,
  TabProps,
  TabPanelProps,
  TabsActivation,
  TabsOrientation,
} from './primitives/Tabs';
export { Tooltip } from './primitives/Tooltip';
export type { TooltipProps } from './primitives/Tooltip';
export { Dialog, DialogHeader, DialogBody, DialogFooter, DialogClose } from './primitives/Dialog';
export type {
  DialogProps,
  DialogHeaderProps,
  DialogBodyProps,
  DialogFooterProps,
  DialogCloseProps,
  DialogRole,
  DialogSize,
} from './primitives/Dialog';
export { ToastProvider, useToast } from './primitives/Toast';
export type {
  ToastAction,
  ToastApi,
  ToastOptions,
  ToastPlacement,
  ToastProviderProps,
  ToastRecord,
  ToastTone,
} from './primitives/Toast';
export { Popover, PopoverTrigger, PopoverContent } from './primitives/Popover';
export type { PopoverProps, PopoverTriggerProps, PopoverContentProps } from './primitives/Popover';
export { Menu, MenuTrigger, MenuContent, MenuItem, MenuSeparator, MenuGroup } from './primitives/Menu';
export type {
  MenuProps,
  MenuTriggerProps,
  MenuContentProps,
  MenuItemProps,
  MenuSeparatorProps,
  MenuGroupProps,
} from './primitives/Menu';
export { Combobox } from './primitives/Combobox';
export type {
  ComboboxItem,
  ComboboxProps,
  ComboboxSelectionBehaviour,
} from './primitives/Combobox';
export { Progress } from './primitives/Progress';
export type { ProgressProps, ProgressSize, ProgressTone } from './primitives/Progress';
export { Skeleton } from './primitives/Skeleton';
export type { SkeletonDirection, SkeletonProps, SkeletonShape } from './primitives/Skeleton';
export { ScrollArea } from './primitives/ScrollArea';
export type { ScrollAreaProps, ScrollAreaOrientation } from './primitives/ScrollArea';
export { PaneGroup, Pane, PaneHandle, resizeAt } from './primitives/ResizablePane';
export type {
  PaneGroupProps,
  PaneProps,
  PaneHandleProps,
  PaneDirection,
} from './primitives/ResizablePane';
export { VirtualList } from './primitives/VirtualList';
export type {
  VirtualListProps,
  VirtualListHandle,
  VirtualListRole,
  ScrollAlignment,
} from './primitives/VirtualList';

// Behaviour hooks - the same contracts the primitives above are built from
export {
  useId,
  useOptionalId,
  usePortal,
  useReducedMotion,
  useFocusTrap,
  useDismiss,
  useRovingTabIndex,
  useAnchorPosition,
  computeAnchorPosition,
  useControllableState,
  getTabbable,
  focusElement,
  isDisabledElement,
  isFocusVisible,
} from './hooks';
export type {
  UsePortalOptions,
  UseFocusTrapOptions,
  DismissReason,
  UseDismissOptions,
  RovingOrientation,
  RovingTabIndexApi,
  UseRovingTabIndexOptions,
  AnchorAlignment,
  AnchorPlacement,
  AnchorPosition,
  AnchorRect,
  ComputeAnchorPositionInput,
  UseAnchorPositionOptions,
  UseAnchorPositionResult,
  SetControllableState,
  UseControllableStateOptions,
} from './hooks';

// Error and async-state language
export {
  AsyncState,
  SafetyStatement,
  ErrorNotice,
  ResearchState,
  describeResearchState,
  ASYNC_STATE_META,
  SAFETY_SENTENCE,
} from './states';
export type {
  AsyncStateProps,
  AsyncStateKind,
  AsyncStateMeta,
  ErrorNoticeKind,
  ErrorNoticeProps,
  ResearchStateCase,
  ResearchStateProps,
  ResearchStatePresentation,
  SafetyNote,
  SafetyStatus,
  StateAction,
} from './states';

// manuscript, workspace composition, theme provider (DS2b)
export {
  FileTree,
  SourceEditorFrame,
  PdfPreview,
  CompilerStatus,
  CompilerDiagnostic,
  CompilerDiagnosticList,
  AuditFinding,
  AuditFindingList,
  DiagnosticsPanel,
  CandidateDiff,
  AUDIT_KIND_META,
  AUDIT_SEVERITY_META,
  BUILD_STATUS_META,
  DIAGNOSTIC_SEVERITY_META,
  FILE_KIND_LABELS,
  describeAuditKind,
  fileKindIcon,
  flattenFileTree,
  formatDuration,
  formatTimestamp,
} from './manuscript';
export type {
  FileTreeProps,
  SourceEditorFrameProps,
  PdfPreviewProps,
  CompilerStatusProps,
  CompilerDiagnosticProps,
  CompilerDiagnosticListProps,
  AuditFindingProps,
  AuditFindingListProps,
  DiagnosticsPanelProps,
  CandidateDiffProps,
  DiffView,
  AuditFindingModel,
  BuildModel,
  BuildStatus,
  CandidateDiffModel,
  DiagnosticModel,
  DiagnosticSeverity,
  DiffHunk,
  DiffLine,
  DiffLineKind,
  EditorFrameState,
  FileKind,
  FileNode,
  FlatFileRow,
  SemanticSummary,
} from './manuscript';

export {
  ThemeProvider,
  useTheme,
  useOptionalTheme,
  THEME_STORAGE_KEY,
  AppShell,
  ProjectRail,
  ConversationWorkspace,
  ResearchInspector,
  FullPageWorkspace,
  ManuscriptWorkspace,
  INSPECTOR_TABS,
  INSPECTOR_TAB_META,
  PROJECT_AVAILABILITY_META,
  PROVIDER_STATE_META,
  SELECTION_KIND_META,
  mergePaneSizes,
  resolvePaneSizes,
} from './workspace';
export type {
  ThemeContextValue,
  ThemeProviderProps,
  AppShellProps,
  ProjectRailProps,
  ConversationWorkspaceProps,
  ResearchInspectorProps,
  FullPageWorkspaceProps,
  ManuscriptWorkspaceProps,
  ManuscriptView,
  InspectorRef,
  InspectorSelection,
  InspectorTab,
  PaneSizes,
  ProjectAction,
  ProjectAvailability,
  ProjectModel,
  ProviderStatus,
  RailItem,
} from './workspace';

// research semantics and conversation (DS2a)
export {
  AuthorityBadge,
  EntityRef,
  SourceAnchor,
  EvidenceCard,
  ClaimCard,
  ChangeList,
  ProvenancePath,
  ContextReceipt,
  ReviewDecisionBar,
  ConflictNotice,
  SaveToCorpusAction,
  AUTHORITY_LABELS,
  CHANGE_KINDS,
  CHANGE_KIND_META,
  ENTITY_KINDS,
  ENTITY_KIND_META,
  RESOLUTION_META,
  CONTEXT_CLASSES,
  CONTEXT_CLASS_META,
  OMISSION_REASONS,
  OMISSION_REASON_META,
  EGRESS_META,
  REVIEW_DECISIONS,
  REVIEW_DECISION_META,
  formatAnchorTarget,
  ANCHOR_STATUS_META,
  CANDIDATE_FIELD_META,
  CLAIM_RELATION_META,
  CLAIM_SCOPE_META,
  CLAIM_STATUS_META,
  CLAIM_TYPE_META,
  CONFLICT_KIND_META,
  DECISION_STATUS_META,
  DECISION_TYPE_META,
  EVIDENCE_ORIGIN_META,
  EVIDENCE_STATUS_META,
  EVIDENCE_STRENGTH_META,
  EVIDENCE_TYPE_META,
  NEGATIVE_STATE_META,
  OVERTURN_RISK_META,
  QUESTION_STATUS_META,
  RESEARCH_VOCABULARIES,
  REVIEW_CATEGORY_META,
  REVIEW_TIER_META,
  SCREENING_STATE_META,
  STALE_STATE_META,
  VERIFICATION_VERDICT_META,
  humaniseResearchTokens,
  humaniseTerm,
  researchDescription,
  researchLabel,
  termDescription,
  termLabel,
} from './research';
export type {
  AuthorityBadgeProps,
  EntityRefProps,
  EntityRefElement,
  EntityRefSize,
  SourceAnchorProps,
  SourceAnchorVariant,
  EvidenceCardProps,
  ClaimCardProps,
  ChangeKind,
  ChangeKindMeta,
  ChangeListEntry,
  ChangeListProps,
  ProvenancePathProps,
  ProvenancePathOrientation,
  ContextReceiptProps,
  ReviewDecisionBarProps,
  ConflictNoticeProps,
  SaveToCorpusActionProps,
  SaveToCorpusCorpusLinks,
  AuthorityLabel,
  Visibility,
  EntityKind,
  ResolutionState,
  EntityRefModel,
  SourceAnchorModel,
  EvidenceModel,
  EvidenceNumeric,
  ClaimModel,
  ClaimSupport,
  ProvenanceStep,
  ProvenancePathModel,
  ContextClass,
  ContextItem,
  OmittedContextItem,
  ContextAllocation,
  ContextReceiptModel,
  OmissionReason,
  EgressClass,
  ReviewDecision,
  ReviewDecisionMeta,
  ConflictNoticeModel,
  SaveToCorpusState,
  IdentityChoice,
  KindMeta,
  ResolutionMeta,
  TermMeta,
  Vocabulary,
  VocabularyName,
} from './research';

export {
  Message,
  MessageContent,
  Composer,
  ReferencePicker,
  AttachmentTray,
  ImageAttachment,
  PdfAttachment,
  ModelSelector,
  SessionList,
  ATTACHMENT_STATES,
  ATTACHMENT_STATE_META,
  MESSAGE_ROLE_META,
  PROMOTION_TARGETS,
  PROMOTION_TARGET_META,
  canSaveToCorpus,
  formatFileSize,
  formatMessageTime,
} from './conversation';
export type {
  MessageProps,
  MessageElement,
  MessageContentProps,
  ComposerProps,
  ReferencePickerProps,
  AttachmentTrayProps,
  AttachmentSaveModel,
  ImageAttachmentProps,
  PdfAttachmentProps,
  ModelSelectorProps,
  SessionListProps,
  MessageRole,
  MessageStatus,
  MessageBlock,
  MessageModel,
  RoleMeta,
  AttachmentState,
  AttachmentStateMeta,
  AttachmentModel,
  AttachmentSendability,
  AttachmentCorpusLinks,
  PromotionTarget,
  ModelOption,
  ModelOptionGroup,
  SessionSummary,
  ComposerValue,
  ComposerBlockedReason,
  ComposerSendState,
} from './conversation';
