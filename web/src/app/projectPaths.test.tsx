/**
 * Task 10.1: one prefix, applied in one place.
 *
 * The invariant under test is that a view written against `href()` produces the legacy URL
 * when there is no project and the project URL when there is — without the view knowing
 * which host it is inside. The default context is the legacy one on purpose: a component
 * mounted outside a provider must keep the links it has always had.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProjectPathProvider, projectHref, useProjectPaths } from './projectPaths';

function Probe() {
  const { projectId, href } = useProjectPaths();
  return (
    <dl>
      <dt>id</dt>
      <dd data-testid="id">{projectId ?? 'none'}</dd>
      <dt>claim</dt>
      <dd data-testid="claim">{href('/claims/C0001')}</dd>
      <dt>session</dt>
      <dd data-testid="session">{href('/?session=CS0001')}</dd>
    </dl>
  );
}

describe('projectHref', () => {
  it('prefixes a workspace path and preserves its query', () => {
    expect(projectHref('prj_abc', '/?session=CS0001')).toBe('/projects/prj_abc/?session=CS0001');
    expect(projectHref('prj_abc', '/claims/C0001')).toBe('/projects/prj_abc/claims/C0001');
  });

  it('leaves a path alone when there is no project', () => {
    expect(projectHref(null, '/claims/C0001')).toBe('/claims/C0001');
    expect(projectHref(null, '/?session=CS0001')).toBe('/?session=CS0001');
  });

  it('encodes an id rather than letting it shape the URL', () => {
    expect(projectHref('a/b', '/claims/C0001')).toBe('/projects/a%2Fb/claims/C0001');
  });

  it('accepts a path written without its leading slash', () => {
    expect(projectHref('prj_abc', 'claims/C0001')).toBe('/projects/prj_abc/claims/C0001');
  });
});

describe('useProjectPaths', () => {
  it('is the identity outside a provider, so legacy views are untouched', () => {
    render(<Probe />);
    expect(screen.getByTestId('id')).toHaveTextContent('none');
    expect(screen.getByTestId('claim')).toHaveTextContent('/claims/C0001');
    expect(screen.getByTestId('session')).toHaveTextContent('/?session=CS0001');
  });

  it('prefixes every path inside a project provider', () => {
    render(
      <ProjectPathProvider projectId="prj_abc">
        <Probe />
      </ProjectPathProvider>,
    );
    expect(screen.getByTestId('id')).toHaveTextContent('prj_abc');
    expect(screen.getByTestId('claim')).toHaveTextContent('/projects/prj_abc/claims/C0001');
    expect(screen.getByTestId('session')).toHaveTextContent('/projects/prj_abc/?session=CS0001');
  });

  it('falls back to the legacy paths when a provider carries no project', () => {
    render(
      <ProjectPathProvider projectId={null}>
        <Probe />
      </ProjectPathProvider>,
    );
    expect(screen.getByTestId('claim')).toHaveTextContent('/claims/C0001');
  });
});
