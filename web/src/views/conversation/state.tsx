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
import type {
  EntityRefModel,
  InspectorRef,
  InspectorTab,
  SourceAnchorModel,
} from '@research-harness/design';
import { useProjectPaths } from '../../app/projectPaths';
import { useSession } from '../../app/session';
import {
  CONVERSATION_PATH,
  bindingOptionId,
  entityRefFor,
  parseRuntimeOptionId,
  routeForEntity,
} from './mappers';
/* References and the graph (task W3): completion, token resolution and `rh://` links. */
import { SOURCE_PATH, useDeepLinks, useGraphReferences, useResolveReferences } from './references';
import type { DeepLinkApi, GraphReferencesApi, ResolveReferencesApi } from './references';
import { useDraft } from './useDraft';
import type { DraftApi } from './useDraft';
import { useModels } from './useModels';
import type { ModelsApi } from './useModels';
import { indexReferenceProvider, useReferenceQuery } from './useReferenceQuery';
import type { ReferenceProvider, ReferenceQueryApi } from './useReferenceQuery';
import { useSend } from './useSend';
import type { SendApi } from './useSend';
/* Attachments (task W2): one list, one send check and one save flow, shared by the
   composer's tray, the transcript's rows and the inspector's entry. */
import { useAttachmentWorkspace } from './attachments/useAttachments';
import type { AttachmentWorkspace } from './attachments/useAttachments';
import { usePdfPageRenderer } from './attachments/AttachmentViewer';
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
  /**
   * The composer draft. Its `tokens` carry what `graph.resolve` said about each of them,
   * so an unresolved, stale, private or broken reference is marked in the composer before
   * it is sent (task W3, conversation spec §7). The words themselves are never touched.
   */
  draft: DraftApi;
  references: ReferenceQueryApi;
  /**
   * Which index answers `@` completion, and — when it is not the graph — why not. The
   * composer renders the reason once; the fallback provider is already in place.
   */
  graph: GraphReferencesApi;
  /** What `graph.resolve` said about each token in the draft, before it is sent. */
  draftReferences: ResolveReferencesApi;
  /** `rh://` links: resolved against canonical state, then navigated or explained. */
  deepLinks: DeepLinkApi;
  /** Open one exact place inside a source artifact: page, block, highlighted. */
  openAnchor: (anchor: SourceAnchorModel) => void;
  /**
   * The session's attachments (task W2): the tray's list and intake, the per-item verdict
   * for the selected model, and the `Save to corpus` flow. Shared rather than per-surface
   * because the composer, the transcript and the inspector must agree about one file.
   */
  attachments: AttachmentWorkspace;
  /** Renders one page of a session PDF, for any surface that shows a PDF attachment. */
  renderAttachmentPage: (attachmentId: string, pageIndex: number) => ReactNode;
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

/** One identity for "this session has no attachments", so nothing re-runs on every render. */
const EMPTY_ATTACHMENTS: never[] = [];

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
   * Where `@` completion looks.
   *
   * The default is now the graph: `graph.autocomplete` with W1's `indexReferenceProvider`
   * behind it, chosen by `graph.status` (task W3). Passing one here overrides both, which
   * is what a test and an embedding host want.
   */
  referenceProvider?: ReferenceProvider;
}

export function ConversationProvider({ children, referenceProvider }: ConversationProviderProps) {
  const { client, overview, canMutate, mutationBlockedReason } = useSession();
  const { projectId, href } = useProjectPaths();
  const location = useLocation();
  const navigate = useNavigate();
  // `/` under the legacy host, `/projects/{id}/` under the multi-project one — the same
  // screen either way, so the comparison is made against this tree's own conversation path
  // rather than against a literal. A trailing slash is not a different route.
  const active = samePath(location.pathname, href(CONVERSATION_PATH));

  // Keyed by the stable project id under a multi-project host, so relocating a project
  // changes its root without discarding the session it remembered (design §11); the legacy
  // host has no id and keys by the workspace path exactly as before.
  const sessions = useSessions(client, {
    project: projectId ?? overview?.workspace ?? null,
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

  /* References and the graph (task W3) ------------------------------------------------
   *
   * The provider swap of W1's seam: `graph.autocomplete` completes over every namespace
   * the projection holds, and W1's `indexReferenceProvider` stays mounted behind it as the
   * fallback `graph.status` selects when the index is absent, rebuilding or unreadable
   * (graph spec §8). A host may still pass its own provider, which then wins outright. */
  const fallbackProvider = useMemo(() => indexReferenceProvider(client, href), [client, href]);
  const sessionVisibility = sessions.active?.visibility ?? null;
  const graphVisibility = useMemo(
    () => (sessionVisibility === 'project' ? (['project'] as const) : undefined),
    [sessionVisibility],
  );
  const graph = useGraphReferences(client, {
    fallback: fallbackProvider,
    enabled: active,
    ...(graphVisibility ? { visibility: graphVisibility } : {}),
  });
  const provider = referenceProvider ?? graph.provider;
  const references = useReferenceQuery(provider);

  const [selection, setSelection] = useState<WorkspaceSelection | null>(null);
  const [following, setFollowing] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(wideEnoughForTheInspector);
  const [tab, setTab] = useState<InspectorTab>('context');
  const [receipt, setReceipt] = useState<ReceiptSource | null>(null);
  const [model, setModel] = useState<string | null>(null);

  /**
   * Where the next message would actually go, for the attachment check.
   *
   * The per-message model when a read-only window chose one; otherwise the session's own
   * binding, which is what the router would resolve. An entry binding names a configured
   * entry, which is what `attachment.check_send` matches on. A *runtime* binding names no
   * configured entry — the daemon builds that route itself on send (plan ruling 2) — so
   * the check is asked with no provider at all, which is the request that means "the entry
   * the router would choose". Naming one here would be this cockpit deciding routing.
   */
  const destination = useMemo(() => {
    if (model) return model;
    const bound = sessions.active ? bindingOptionId(sessions.active.defaults) : null;
    return bound === null || parseRuntimeOptionId(bound) !== null ? null : bound;
  }, [model, sessions.active]);

  /* Attachments (task W2). The transcript's records are the list's starting point, so an
     upload and a re-read of the session converge on one set of files rather than two; the
     ids past messages already carry belong to those turns and are not offered again. */
  const attachmentsInTranscript = useMemo(
    () => (transcript.transcript?.messages ?? []).flatMap((message) => message.attachments ?? []),
    [transcript.transcript],
  );
  const attachments = useAttachmentWorkspace(client, sessionId, {
    records: transcript.transcript?.attachments ?? EMPTY_ATTACHMENTS,
    usedIds: attachmentsInTranscript,
    canMutate,
    blockedReason: mutationBlockedReason,
    model: destination,
    enabled: active,
  });
  const renderAttachmentPage = usePdfPageRenderer(client, sessionId);

  /* Every token in the draft, resolved against canonical state before it is sent (task
     W3). The marks ride on the draft's own tokens, so the composer needs no change: it
     renders `value.tokens`, and those are now the resolved ones. A flagged token stays
     sendable — `references` on `session.send` is still every id the researcher chose. */
  const resolution = useResolveReferences(client, draft.value.tokens, {
    unresolved: send.unresolved,
    session: sessionId,
    enabled: active,
  });
  const resolvedDraft = useMemo<DraftApi>(
    () => ({
      ...draft,
      value: { ...draft.value, tokens: resolution.tokens },
    }),
    [draft, resolution.tokens],
  );

  /* `rh://` links, resolved before anything navigates (plan §0.1). */
  const deepLinks = useDeepLinks(client, { session: sessionId });

  /** Open a source anchor at its exact page and block. */
  const openAnchor = useCallback(
    (anchor: SourceAnchorModel) => {
      const query = new URLSearchParams();
      if (anchor.page !== undefined) query.set('page', String(anchor.page));
      if (anchor.block !== undefined) query.set('block', anchor.block);
      const suffix = query.toString();
      navigate(
        href(`${SOURCE_PATH}/${encodeURIComponent(anchor.artifactId)}${suffix ? `?${suffix}` : ''}`),
      );
    },
    [href, navigate],
  );

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
        navigate(routeForEntity('session', ref.id, {}, href) ?? href(CONVERSATION_PATH));
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
    [href, navigate, selectMessage, selectReference],
  );

  const navigateTo = useCallback(
    (ref: InspectorRef) => {
      // `ref.href` was built for this tree by whoever produced the chip, so it is taken as
      // it is; only the route derived here has to be prefixed, and exactly once.
      const target =
        ref.href ??
        routeForEntity(entityRefFor(ref.id).kind, ref.id, { session: sessionId }, href) ??
        null;
      if (target) navigate(target);
    },
    [href, navigate, sessionId],
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
    draft: resolvedDraft,
    references,
    graph,
    draftReferences: resolution,
    deepLinks,
    openAnchor,
    attachments,
    renderAttachmentPage,
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

/** Two in-app paths naming the same route; a trailing slash is not a difference. */
function samePath(a: string, b: string): boolean {
  const trim = (path: string): string => (path.length > 1 ? path.replace(/\/$/, '') : path);
  return trim(a) === trim(b);
}

/** The same state, or null — for a shell slot that renders on every route. */
export function useOptionalConversation(): ConversationState | null {
  return useContext(Context);
}
