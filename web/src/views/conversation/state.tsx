/**
 * The conversation workspace's shared state.
 *
 * Three surfaces need the same session: the rail's history (`SessionList`, in the shell),
 * the centre pane (the transcript and the composer, in the route), and the inspector (in
 * the shell again, because `AppShell` owns the narrow-screen drawer that keeps the draft
 * mounted). They are in three different places in the tree, so the state they share is a
 * context rather than props — the alternative is lifting the whole workspace into
 * `Layout.tsx`, which would put research reads in the shell every other route also uses.
 *
 * The provider is mounted for the whole cockpit because the session history belongs to the
 * rail on every screen (workspace design §2). Everything that only the conversation needs
 * — the transcript, the model catalogue, the run subscription — is gated on `active`, so a
 * researcher on `/claims` pays for one `session.list` and nothing else.
 */
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { EntityRefModel, InspectorRef, InspectorTab } from '@research-harness/design';
import { useSession } from '../../app/session';
import { CONVERSATION_PATH, entityRefFor, routeForEntity } from './mappers';
import { useDraft } from './useDraft';
import type { DraftApi } from './useDraft';
import { useModels } from './useModels';
import type { ModelsApi } from './useModels';
import { indexReferenceProvider, useReferenceQuery } from './useReferenceQuery';
import type { ReferenceProvider, ReferenceQueryApi } from './useReferenceQuery';
import { useSend } from './useSend';
import type { SendApi } from './useSend';
import { useSessions } from './useSessions';
import type { SessionsApi } from './useSessions';
import { useTranscript } from './useTranscript';
import type { TranscriptApi } from './useTranscript';

/** What the inspector is following, in the cockpit's own terms. */
export type WorkspaceSelection =
  | { kind: 'message'; messageId: string }
  | { kind: 'reference'; ref: EntityRefModel };

/** Which receipt the Context tab is showing, and where it came from. */
export type ReceiptSource =
  | { kind: 'recorded'; packId: string }
  | { kind: 'draft'; text: string; references: string[]; model: string | null };

export interface ConversationState {
  /** True while the conversation route is the one on screen. */
  active: boolean;
  sessions: SessionsApi;
  transcript: TranscriptApi;
  send: SendApi;
  models: ModelsApi;
  draft: DraftApi;
  references: ReferenceQueryApi;
  selection: WorkspaceSelection | null;
  selectMessage: (messageId: string) => void;
  selectReference: (ref: EntityRefModel) => void;
  following: boolean;
  setFollowing: (following: boolean) => void;
  inspectorOpen: boolean;
  setInspectorOpen: (open: boolean) => void;
  tab: InspectorTab;
  setTab: (tab: InspectorTab) => void;
  receipt: ReceiptSource | null;
  showReceipt: (source: ReceiptSource | null) => void;
  /** Open a reference: the inspector follows it, and a full page is one click further. */
  openRef: (ref: EntityRefModel) => void;
  /** The inspector's "Open" button and any panel row: leave for the object's own screen. */
  navigateTo: (ref: InspectorRef) => void;
  /** The selected model id, or null to use the session's default. */
  model: string | null;
  setModel: (model: string | null) => void;
}

const Context = createContext<ConversationState | null>(null);

/** `AppShell`'s default breakpoint: at or below it the side panes are drawers. */
const NARROW = 960;

/**
 * Whether the inspector should start open.
 *
 * Open on a wide screen, where it is a third column. Closed on a narrow one, where it is a
 * drawer over the composer — a research pane that covers the draft on load is exactly what
 * conversation spec §9 forbids. jsdom and SSR have no `matchMedia` and answer "wide",
 * which is the layout they render.
 */
function wideEnoughForTheInspector(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
  try {
    return !window.matchMedia(`(max-width: ${NARROW}px)`).matches;
  } catch {
    return true;
  }
}

export interface ConversationProviderProps {
  children: ReactNode;
  /**
   * Where `@` completion looks. Defaults to the cockpit's own listings; task W3 passes a
   * `graph.autocomplete` provider here and nothing else changes.
   */
  referenceProvider?: ReferenceProvider;
}

export function ConversationProvider({ children, referenceProvider }: ConversationProviderProps) {
  const { client, overview, canMutate } = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const active = location.pathname === CONVERSATION_PATH;

  const sessions = useSessions(client, {
    project: overview?.workspace ?? null,
    canMutate,
  });
  const sessionId = sessions.activeId;
  const transcript = useTranscript(client, sessionId, { enabled: active });
  const send = useSend(client, sessionId, {
    reconcile: transcript.reconcile,
    canMutate,
    enabled: active,
  });
  const models = useModels(client, { enabled: active });
  const draft = useDraft(sessionId);
  const provider = useMemo(
    () => referenceProvider ?? indexReferenceProvider(client),
    [client, referenceProvider],
  );
  const references = useReferenceQuery(provider);

  const [selection, setSelection] = useState<WorkspaceSelection | null>(null);
  const [following, setFollowing] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(wideEnoughForTheInspector);
  const [tab, setTab] = useState<InspectorTab>('context');
  const [receipt, setReceipt] = useState<ReceiptSource | null>(null);
  const [model, setModel] = useState<string | null>(null);

  const selectMessage = useCallback((messageId: string) => {
    setSelection({ kind: 'message', messageId });
  }, []);

  const selectReference = useCallback((ref: EntityRefModel) => {
    setSelection({ kind: 'reference', ref });
  }, []);

  /**
   * A reference in the transcript opens its object *here* first.
   *
   * The inspector shows the object and, beside it, every message that referenced it —
   * which is the second half of spec §2's two-way navigation and the only half that can be
   * done without leaving the conversation. Its header's Open button is the way out to the
   * object's full page.
   */
  const openRef = useCallback(
    (ref: EntityRefModel) => {
      if (ref.kind === 'session') {
        navigate(routeForEntity('session', ref.id) ?? CONVERSATION_PATH);
        return;
      }
      if (ref.kind === 'message') {
        selectMessage(ref.id);
        setTab('context');
        setInspectorOpen(true);
        return;
      }
      selectReference(ref);
      setTab(ref.kind === 'claim' ? 'claims' : ref.kind === 'evidence' ? 'evidence' : 'context');
      setInspectorOpen(true);
    },
    [navigate, selectMessage, selectReference],
  );

  const navigateTo = useCallback(
    (ref: InspectorRef) => {
      const href =
        ref.href ??
        routeForEntity(entityRefFor(ref.id).kind, ref.id, { session: sessionId }) ??
        null;
      if (href) navigate(href);
    },
    [navigate, sessionId],
  );

  const showReceipt = useCallback((source: ReceiptSource | null) => {
    setReceipt(source);
    if (source) {
      setTab('context');
      setInspectorOpen(true);
    }
  }, []);

  const value: ConversationState = {
    active,
    sessions,
    transcript,
    send,
    models,
    draft,
    references,
    selection,
    selectMessage,
    selectReference,
    following,
    setFollowing,
    inspectorOpen,
    setInspectorOpen,
    tab,
    setTab,
    receipt,
    showReceipt,
    openRef,
    navigateTo,
    model,
    setModel,
  };

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The workspace state. Throws outside the provider, like `useSession`. */
export function useConversation(): ConversationState {
  const state = useContext(Context);
  if (!state) throw new Error('useConversation must be used inside a ConversationProvider');
  return state;
}

/** The same state, or null — for a shell slot that renders on every route. */
export function useOptionalConversation(): ConversationState | null {
  return useContext(Context);
}
