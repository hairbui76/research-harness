/**
 * The research navigation, pointed at one project.
 *
 * The rail and the router read one list (`routes.tsx`), and under the multi-project host
 * every workspace screen lives below `/projects/{project_id}` (design §4.5). So the only
 * thing that may differ between the two hosts is where the list's `to` values point, and
 * these tests pin exactly that: the prefix is applied once, to every entry, and nothing
 * else about an entry moves.
 */
import { describe, expect, it } from 'vitest';
import { NAVIGATION, navigationForProject, OVERVIEW_PATH } from './routes';

describe('navigationForProject', () => {
  it('is the legacy navigation, untouched, when there is no project', () => {
    // Identity, not just equality: the rail memoises on it, and a fresh array every render
    // would rebuild the whole rail on a host that has no projects at all.
    expect(navigationForProject(null)).toBe(NAVIGATION);
    expect(navigationForProject(null).map((entry) => entry.to)).toEqual([
      '/',
      OVERVIEW_PATH,
      '/review',
      '/conflicts',
      '/stale',
      '/corpus',
      '/claims',
      '/questions',
      '/synthesis',
      '/taxonomy',
      '/manuscript',
    ]);
  });

  it('keeps rail navigation inside the active project', () => {
    const rail = navigationForProject('prj_abc');

    expect(rail.find((entry) => entry.id === 'corpus')?.to).toBe('/projects/prj_abc/corpus');
    expect(rail.find((entry) => entry.id === 'claims')?.to).toBe('/projects/prj_abc/claims');
    expect(rail.find((entry) => entry.id === 'overview')?.to).toBe('/projects/prj_abc/overview');
    // The conversation is the root of the workspace, so it is the project's own root.
    expect(rail.find((entry) => entry.id === 'conversation')?.to).toBe('/projects/prj_abc/');
    expect(rail.every((entry) => entry.to.startsWith('/projects/prj_abc'))).toBe(true);
  });

  it('changes where an entry points and nothing else about it', () => {
    const rail = navigationForProject('prj_abc');

    expect(rail.map((entry) => entry.id)).toEqual(NAVIGATION.map((entry) => entry.id));
    expect(rail.map((entry) => entry.label)).toEqual(NAVIGATION.map((entry) => entry.label));
    expect(rail.map((entry) => entry.icon)).toEqual(NAVIGATION.map((entry) => entry.icon));
    expect(rail.map((entry) => entry.end)).toEqual(NAVIGATION.map((entry) => entry.end));
    // An entry that matched no extra paths does not acquire an empty list of them.
    expect(rail.every((entry) => entry.alsoMatches === undefined)).toBe(true);
  });

  it('prefixes every extra path an entry counts as active for', () => {
    // No entry carries `alsoMatches` today, and the rule still has to hold the day one
    // does: an entry active on `/corpus/W0001` must be active on the project's own copy of
    // it, or opening a Work would drop the rail's highlight.
    NAVIGATION.push({
      id: 'test-only',
      label: 'Test only',
      to: '/corpus',
      icon: 'library',
      alsoMatches: ['/corpus/W0001', '/evidence/E0001'],
    });
    try {
      const entry = navigationForProject('prj_abc').at(-1)!;
      expect(entry.to).toBe('/projects/prj_abc/corpus');
      expect(entry.alsoMatches).toEqual([
        '/projects/prj_abc/corpus/W0001',
        '/projects/prj_abc/evidence/E0001',
      ]);
      expect(navigationForProject(null).at(-1)!.alsoMatches).toEqual([
        '/corpus/W0001',
        '/evidence/E0001',
      ]);
    } finally {
      NAVIGATION.pop();
    }
  });

  it('escapes a project id so it can only ever be one path segment', () => {
    expect(navigationForProject('a/b')[1]!.to).toBe('/projects/a%2Fb/overview');
  });

  it('leaves the shared navigation table alone', () => {
    navigationForProject('prj_abc');
    expect(NAVIGATION.find((entry) => entry.id === 'corpus')?.to).toBe('/corpus');
  });
});
