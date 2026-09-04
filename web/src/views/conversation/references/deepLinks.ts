/**
 * `rh://` deep links: resolve first, navigate second.
 *
 * Plan §0.1 and graph spec §5 put the rule plainly — *the resolver validates the project,
 * the object's existence, authority, privacy, and anchor freshness before anything
 * navigates to or includes the target*. So a link in a message is not a URL this cockpit
 * follows. It is a question asked of `graph.resolve`, and only an answer that says the
 * object is there, in this project, and still where its anchor says it is, turns into a
 * route.
 *
 * What happens otherwise is the point of the feature: a link that cannot be followed
 * **explains itself** in the daemon's own words, rather than navigating to a plausible page
 * or silently doing nothing. When the object exists but something else objects — an anchor
 * that moved, a private target — the explanation carries an "Open anyway" route, because a
 * researcher who has read *why* is entitled to look. When it does not exist, there is
 * nowhere to go and nothing is offered.
 *
 * Where each kind lands:
 *
 * | link | route |
 * |---|---|
 * | `rh://artifact/A0017-3?page=6&block=B0081` | `/source/A0017-3?page=6&block=B0081` — the page with the block highlighted |
 * | `rh://artifact/A0017-3` | the Work's corpus page, which is where an artifact with no place inside it belongs |
 * | `rh://evidence/E0482`, `claim`, `work`, `version`, `question`, `decision` | their own pages, through `routeForEntity` |
 * | `rh://session/CS0001?message=M0042` | `/?session=CS0001&message=M0042` |
 * | `rh://attachment/SA0003` | the session that holds it, with the attachment selected |
 * | `rh://manuscript/main.tex?line=120` | `/manuscript?file=main.tex&line=120` |
 */
import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { HarnessClient } from '../../../api/client';
import type { GraphResolvedView } from '../../../api/dto';
import type { DeepLink } from '../../../render';
import { CONVERSATION_PATH, routeForDeepLink } from '../mappers';
import type { PathHref } from '../mappers';
import { useProjectPaths } from '../../../app/projectPaths';

/** Where one artifact's own bytes are read at an exact page and block. */
export const SOURCE_PATH = '/source';

/** Where the manuscript workspace lives; `?file=` and `?line=` open it at a position. */
export const MANUSCRIPT_PATH = '/manuscript';

export interface DeepLinkContext {
  /** The session on screen, so an attachment link that names none still lands somewhere. */
  session?: string | null;
}

/**
 * The route a *resolved* link opens, or null when this cockpit has no screen for it.
 *
 * `view` is consulted only for what the graph knows and the link text does not — which
 * session an attachment belongs to. Nothing about authority or freshness is decided here;
 * that is `followable` below, and it reads the daemon's answer.
 */
export function routeForResolvedLink(
  link: DeepLink,
  view: GraphResolvedView | null,
  context: DeepLinkContext = {},
  href: PathHref = (path) => path,
): string | null {
  switch (link.kind) {
    case 'artifact': {
      const page = link.params.get('page');
      const block = link.params.get('block');
      if (!page && !block) return routeForDeepLink(link, href);
      const query = new URLSearchParams();
      if (page) query.set('page', page);
      if (block) query.set('block', block);
      return href(`${SOURCE_PATH}/${encodeURIComponent(link.id)}?${query.toString()}`);
    }
    case 'attachment': {
      const session = sessionOfAttachment(view) ?? context.session ?? null;
      return session === null
        ? null
        : href(
            `${CONVERSATION_PATH}?session=${encodeURIComponent(session)}` +
              `&attachment=${encodeURIComponent(link.id)}`,
          );
    }
    case 'manuscript': {
      const query = new URLSearchParams({ file: link.id });
      const line = link.params.get('line');
      if (line) query.set('line', line);
      return href(`${MANUSCRIPT_PATH}?${query.toString()}`);
    }
    default:
      return routeForDeepLink(link, href);
  }
}

/** The session a resolved attachment node says it belongs to. */
function sessionOfAttachment(view: GraphResolvedView | null): string | null {
  const session = view?.node?.metadata.session;
  return typeof session === 'string' ? session : null;
}

/**
 * Whether a resolved link may be followed without saying anything first.
 *
 * The same three questions `ResolvedView.ok` answers on the daemon, asked here so the
 * cockpit does not have to trust a property it did not receive: does it exist, does its
 * anchor still hold, and did the resolver record any other objection.
 */
export function followable(view: GraphResolvedView): boolean {
  return view.exists && view.fresh && view.problems.length === 0;
}

/** A link that was not followed, and everything known about why. */
export interface DeepLinkProblem {
  link: DeepLink;
  /** The resolver's answer, or null when it could not be asked. */
  view: GraphResolvedView | null;
  /** The daemon's own sentences. Never a sentence this client wrote about the object. */
  problems: readonly string[];
  /** Where "Open anyway" would go, when the object exists and this cockpit has a screen. */
  href: string | null;
}

export interface DeepLinkApi {
  /** Resolve this link and navigate, or raise a problem. */
  open: (link: DeepLink) => void;
  /** True while a link is being resolved. */
  opening: boolean;
  /** The link that could not be followed, or null. */
  problem: DeepLinkProblem | null;
  dismiss: () => void;
  /** Follow the raised link anyway. Only ever offered when `problem.href` is set. */
  openAnyway: () => void;
}

/**
 * The resolver behind every `rh://` link in a message.
 *
 * A transport failure is treated exactly like a refusal: the link is not followed and the
 * failure is shown. Navigating on a resolve that never answered would be the one thing this
 * seam exists to prevent.
 */
export function useDeepLinks(client: HarnessClient, context: DeepLinkContext = {}): DeepLinkApi {
  const navigate = useNavigate();
  // The route a resolved link opens is a workspace path; which tree it is opened in is this
  // window's business, not the link's, so the prefix is applied here and nowhere upstream.
  const { href: prefix } = useProjectPaths();
  const [opening, setOpening] = useState(false);
  const [problem, setProblem] = useState<DeepLinkProblem | null>(null);
  const session = context.session ?? null;

  const open = useCallback(
    (link: DeepLink) => {
      setOpening(true);
      setProblem(null);
      client
        .resolveReference(link.href)
        .then((view) => {
          const href = routeForResolvedLink(link, view, { session }, prefix);
          if (followable(view) && href !== null) {
            navigate(href);
            return;
          }
          setProblem({
            link,
            view,
            problems: view.problems.length > 0 ? view.problems : [noScreen(link, view, href)],
            href: view.exists ? href : null,
          });
        })
        .catch((cause: unknown) => {
          setProblem({
            link,
            view: null,
            problems: [
              `The daemon could not resolve ${link.href}: ${
                cause instanceof Error ? cause.message : String(cause)
              }`,
            ],
            href: null,
          });
        })
        .finally(() => setOpening(false));
    },
    [client, navigate, prefix, session],
  );

  const openAnyway = useCallback(() => {
    const href = problem?.href;
    setProblem(null);
    if (href) navigate(href);
  }, [navigate, problem]);

  return { open, opening, problem, dismiss: () => setProblem(null), openAnyway };
}

/** Why a link the resolver was happy with still did not open. */
function noScreen(link: DeepLink, view: GraphResolvedView, href: string | null): string {
  if (href === null) {
    return `This cockpit has no screen for ${link.href} yet, so it was not opened.`;
  }
  return `${link.href} did not resolve to something that can be opened in ${view.project}.`;
}
