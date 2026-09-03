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
 * It lives beside the deep-link resolver rather than in `src/views/` because it exists to
 * serve `deepLinks.ts` and nothing else; when the corpus grows a browsable artifact reader
 * of its own, this route is what that reader replaces.
 */
import { useParams, useSearchParams } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import type { BlockView, SourceContext } from '../../../api/dto';
import { Empty, ErrorBox, Loading } from '../../../components/Feedback';
import { SourcePane } from '../../../components/SourcePane';
import { useSession } from '../../../app/session';
import { useAsync } from '../../../app/useAsync';

export function ArtifactSourcePage() {
  const { artifactId = '' } = useParams();
  const [params] = useSearchParams();
  const { client } = useSession();
  const state = useAsync(() => client.blocks(artifactId), [client, artifactId]);

  if (state.loading) return <Loading what={`artifact ${artifactId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No artifact {artifactId}.</Empty>;

  const blocks = state.data;
  const blockId = params.get('block');
  const requested = Number.parseInt(params.get('page') ?? '', 10);
  const block = blockId ? (blocks.blocks.find((row: BlockView) => row.id === blockId) ?? null) : null;

  // The block's own page wins over the link's, because the parse knows where the block is
  // and the link is a human-written address that may be a page out of date.
  const page = block?.page ?? (Number.isFinite(requested) ? requested : 1);
  const context: SourceContext = {
    page,
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
          ? `Page ${page}, block ${block.id}. The file is immutable; nothing here is editable.`
          : `Page ${page}. This link named no block, or the stored parse has none by that id.`
      }
    >
      <SourcePane
        artifact={artifactId}
        context={context}
        blocks={blocks}
        blockId={block?.id ?? null}
      />
    </FullPageWorkspace>
  );
}
