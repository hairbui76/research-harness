/**
 * What an address with no page behind it says.
 *
 * `/*` used to render the Overview, so a stale bookmark or a mistyped path showed a
 * plausible wrong page and said nothing about it (critique 2026-09-08, minor observations).
 * That is worse than an error: the reader believes they are where they asked to be, and the
 * only clue is that the project looks different from the one they remember.
 *
 * So the frame stays — this is a research page like any other, and every state of one keeps
 * its heading — and the page says the one true thing it knows: nothing is served at this
 * address. The frame states the condition and the state under it states the address, which
 * is the half a reader cannot see anywhere else and the half a mistyped URL is corrected by
 * seeing. The one way on is the Overview, which is where a researcher with no particular
 * destination belongs.
 *
 * No suggestions and no guessing: the cockpit has no index of what a researcher meant, and
 * a wrong guess offered as a link is how a stale bookmark becomes a wrong page again.
 */
import { Link, useLocation } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import { Empty } from '../components/Feedback';
import { useProjectPaths } from '../app/projectPaths';

export interface NotFoundPageProps {
  /**
   * The one page a reader with no destination belongs on.
   *
   * Passed in rather than imported, so the route table depends on the views and never the
   * other way round: a view that reached back into `routes.tsx` for a path would put a
   * cycle between the router and every screen it mounts.
   */
  overview: string;
}

export function NotFoundPage({ overview }: NotFoundPageProps) {
  const { pathname } = useLocation();
  const { href } = useProjectPaths();
  return (
    <FullPageWorkspace
      title="There is no page at this address"
      description="A link may have outlived the screen it pointed at, or the address may have been mistyped."
    >
      {/* The frame names the condition; the state names the address, which is the half a
          reader cannot see anywhere else on the screen. Neither says the other's sentence. */}
      <Empty
        description="Nothing about the project has changed: only the address is wrong. Every screen the cockpit does serve is listed in the rail."
        action={<Link to={href(overview)}>Go to the Overview</Link>}
      >
        {`Nothing is served at ${pathname}`}
      </Empty>
    </FullPageWorkspace>
  );
}
