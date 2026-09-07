/**
 * `/source/:artifactId?page=6&block=B0081` — where an artifact deep link lands.
 *
 * `rh://artifact/A0017-3?page=6&block=B0081` addresses *an exact place inside a source
 * document* (plan §0.1). Before this route there was nowhere in the cockpit for that to
 * open: the review screen shows a block, but only for a staged candidate, and the corpus
 * page lists a Work's files without opening one. So a link with a page or a block had
 * nothing to resolve to, and the acceptance "the link opens the exact page and block" could
 * not be met.
 *
 * It is deliberately thin. `SourcePane` already renders an artifact's own bytes with the
 * stored block geometry highlighted — the same component and the same parse the review
 * screen uses — so this route reads `GET /blocks/{artifact}` for the parse, builds the
 * `SourceContext` from the block the link names, and hands both over. No new rendering, no
 * new geometry, and no second source of truth about where a block is.
 *
 * The one judgement on the screen is what the drawn span *is*, and that is asked rather
 * than assumed: the resolver says whether the reference this route was opened for carries
 * accepted authority with its anchor still holding, and anything else — including a resolve
 * that could not be made — is a proposal. The accepted tint is a scientific status colour,
 * and this route is reached by links that are not all accepted.
 *
 * It lives beside the deep-link resolver rather than in `src/views/` because it exists to
 * serve `deepLinks.ts` and nothing else; when the corpus grows a browsable artifact reader
 * of its own, this route is what that reader replaces.
 */
import { useParams, useSearchParams } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { BlockView, SourceContext } from '../../../api/dto';
import { Empty, ErrorBox, Loading } from '../../../components/Feedback';
import { SourcePane } from '../../../components/SourcePane';
import type { SpanAuthority } from '../../../components/SourcePane';
import { useSession } from '../../../app/session';
import { useAsync } from '../../../app/useAsync';

export function ArtifactSourcePage() {
  const { artifactId = '' } = useParams();
  const [params] = useSearchParams();
  const { client } = useSession();
  const blockId = params.get('block');
  const page = params.get('page');
  const state = useAsync(async () => {
    const [blocks, authority] = await Promise.all([
      client.blocks(artifactId),
      spanAuthority(client, referenceFor(artifactId, page, blockId)),
    ]);
    return { blocks, authority };
  }, [client, artifactId, page, blockId]);

  if (state.loading) return <Loading what={`artifact ${artifactId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No artifact {artifactId}.</Empty>;

  const { blocks, authority } = state.data;
  const requested = Number.parseInt(page ?? '', 10);
  const block = blockId ? (blocks.blocks.find((row: BlockView) => row.id === blockId) ?? null) : null;

  // The block's own page wins over the link's, because the parse knows where the block is
  // and the link is a human-written address that may be a page out of date.
  const at = block?.page ?? (Number.isFinite(requested) ? requested : 1);
  const context: SourceContext = {
    page: at,
    section_path: block?.section_path ?? [],
    block_text: block?.text ?? '',
    exact_text: block?.text ?? '',
    bbox: block?.bbox ?? null,
    neighbors: [],
  };

  return (
    <FullPageWorkspace
      title={`${blocks.work} · ${artifactId}`}
      description={
        block
          ? `Page ${at}, block ${block.id}. The file is immutable; nothing here is editable.`
          : `Page ${at}. This link named no block, or the stored parse has none by that id.`
      }
    >
      <SourcePane
        artifact={artifactId}
        context={context}
        authority={authority}
        blocks={blocks}
        blockId={block?.id ?? null}
      />
    </FullPageWorkspace>
  );
}

/** The `rh://` reference this route was opened for, rebuilt from the address it landed on. */
function referenceFor(artifactId: string, page: string | null, block: string | null): string {
  const query = new URLSearchParams();
  if (page) query.set('page', page);
  if (block) query.set('block', block);
  const suffix = query.toString();
  return `rh://artifact/${artifactId}${suffix ? `?${suffix}` : ''}`;
}

/**
 * What standing the span drawn on this page has, decided by the daemon and by nothing here.
 *
 * The resolver is the one read that answers existence, authority and anchor freshness
 * against the canonical record, so it is what the accepted tint is allowed to rest on: the
 * mark is accepted only when the reference exists, carries accepted authority, and its
 * anchor still holds exactly where the address says it does. Every other answer — a lower
 * authority, a block that moved, a resolve that could not be made at all — leaves the
 * authority unknown, and unknown is a candidate. It is never the other way round.
 */
async function spanAuthority(client: HarnessClient, reference: string): Promise<SpanAuthority> {
  try {
    const view = await client.resolveReference(reference);
    const accepted =
      view.exists && view.fresh && view.problems.length === 0 && view.authority === 'accepted';
    return accepted ? 'accepted' : 'candidate';
  } catch {
    return 'candidate';
  }
}
