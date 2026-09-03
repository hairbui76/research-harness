/**
 * The cockpit shell: the Product 26 navigation, and the one thing a researcher must always
 * be able to see — whether this window may accept anything.
 */
import { NavLink, Outlet } from 'react-router-dom';
import { useSession } from './session';
import { TokenBar } from './TokenBar';

const NAVIGATION = [
  { to: '/', label: 'Overview', end: true },
  { to: '/review', label: 'Review inbox' },
  { to: '/conflicts', label: 'Conflicts' },
  { to: '/stale', label: 'Stale' },
  { to: '/corpus', label: 'Corpus' },
  { to: '/claims', label: 'Claims' },
  { to: '/questions', label: 'Questions' },
  { to: '/synthesis', label: 'Synthesis' },
  { to: '/taxonomy', label: 'Taxonomy' },
  { to: '/manuscript', label: 'Manuscript' },
];

export function Layout() {
  const { overview, canMutate } = useSession();
  return (
    <div className="shell">
      <nav>
        <div className="brand">
          <strong>Research Harness</strong>
          <span className="muted">{overview?.project ?? 'not connected'}</span>
        </div>
        <ul>
          {NAVIGATION.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.end}>
                {item.label}
                <NavBadge to={item.to} />
              </NavLink>
            </li>
          ))}
        </ul>
        <footer>
          <span className={canMutate ? 'principal human' : 'principal host'}>
            {canMutate ? 'researcher' : 'agent host — read only'}
          </span>
        </footer>
      </nav>
      <main>
        <TokenBar />
        <Outlet />
      </main>
    </div>
  );
}

/** The count the daemon reported for this surface, when it reported one. */
function NavBadge({ to }: { to: string }) {
  const { overview } = useSession();
  const group = overview?.attention.find((entry) => entry.route === to);
  if (!group || group.count === 0) return null;
  return <span className="badge">{group.count}</span>;
}
