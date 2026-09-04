/**
 * The graph mappers, against real `graph.*` payloads.
 *
 * Every fixture under `src/test/fixtures/graph/` was produced from the daemon's own
 * pydantic response models (`capabilities/graph.py`), so a field rename on the Python side
 * fails here rather than at runtime in front of a researcher.
 *
 * What these tests are strict about is the thing the whole task turns on: the mappers carry
 * authority, visibility and edge origin through and *decide nothing*. A candidate relation
 * stays a candidate, a stale row stays stale, and a neighbourhood the daemon pruned stays
 * pruned.
 */
import { describe, expect, it } from 'vitest';
import type { GraphNeighbourhoodView, GraphProvenanceView, GraphResolvedView } from '../../../api/dto';
import type { DeepLink } from '../../../render';
import { parseDeepLink } from '../../../render';
import { projectHref } from '../../../app/projectPaths';
import { routeForResolvedLink } from './deepLinks';
import {
  anchorFrom,
  entityKindOfNodeKind,
  headingFor,
  neighbourGroups,
  provenancePathFrom,
  refFromNode,
  resolutionOf,
} from './mappers';

import neighboursClaim from '../../../test/fixtures/graph/neighbours-claim.json';
import neighboursProject from '../../../test/fixtures/graph/neighbours-claim-project.json';
import provenanceClaim from '../../../test/fixtures/graph/provenance-claim.json';
import provenanceNone from '../../../test/fixtures/graph/provenance-none.json';
import resolveArtifact from '../../../test/fixtures/graph/resolve-artifact-link.json';
import resolveBroken from '../../../test/fixtures/graph/resolve-artifact-broken.json';
import resolveEvidence from '../../../test/fixtures/graph/resolve-evidence.json';
import resolvePrivate from '../../../test/fixtures/graph/resolve-private.json';
import resolveStale from '../../../test/fixtures/graph/resolve-stale.json';
import resolveUnresolved from '../../../test/fixtures/graph/resolve-unresolved.json';

const asResolved = (value: unknown) => value as GraphResolvedView;
const asNeighbourhood = (value: unknown) => value as GraphNeighbourhoodView;
const asProvenance = (value: unknown) => value as GraphProvenanceView;

const link = (href: string): DeepLink => {
  const parsed = parseDeepLink(href);
  if (parsed === null) throw new Error(`${href} is not a deep link`);
  return parsed;
};

describe('resolutionOf', () => {
  it('reports a clean resolve as resolved', () => {
    expect(resolutionOf(asResolved(resolveEvidence))).toBe('resolved');
  });

  it('reports an anchor that moved as stale, not as missing', () => {
    expect(resolutionOf(asResolved(resolveStale))).toBe('stale');
  });

  it('reports a private target as private', () => {
    expect(resolutionOf(asResolved(resolvePrivate))).toBe('private');
  });

  it('reports an `@` id nothing answers to as unresolved, because the index may rebuild', () => {
    expect(resolutionOf(asResolved(resolveUnresolved))).toBe('unresolved');
  });

  it('reports a deep link into a target this project has not got as broken', () => {
    expect(resolutionOf(asResolved(resolveBroken))).toBe('broken');
  });
});

describe('refFromNode', () => {
  it('carries the row’s own authority and label onto the chip', () => {
    const node = asResolved(resolveEvidence).node;
    expect(node).not.toBeNull();
    const ref = refFromNode(node!);
    expect(ref).toMatchObject({
      id: 'E0482',
      kind: 'evidence',
      authority: 'accepted',
      resolution: 'resolved',
      href: '/evidence/E0482',
    });
  });

  it('draws the structure kinds the Design System has no chip for as blocks', () => {
    expect(entityKindOfNodeKind('paragraph')).toBe('block');
    expect(entityKindOfNodeKind('citation')).toBe('block');
    expect(entityKindOfNodeKind('manuscript_file')).toBe('manuscript_file');
    expect(entityKindOfNodeKind('project')).toBeNull();
  });
});

describe('neighbourGroups', () => {
  const groups = neighbourGroups(asNeighbourhood(neighboursClaim));

  it('groups by relation and direction, in the order the graph returned them', () => {
    expect(groups.map((group) => group.key)).toEqual([
      'supports:in',
      'contradicts:in',
      'qualifies:in',
      'mentioned_in:in',
    ]);
    expect(headingFor(groups[0]!)).toBe('Supported by');
    expect(headingFor(groups[3]!)).toBe('Mentioned in messages');
  });

  it('keeps a model-proposed relation a candidate and an accepted one accepted', () => {
    const supports = groups[0]!.neighbours[0]!;
    const contradicts = groups[1]!.neighbours[0]!;
    expect(supports).toMatchObject({ edgeAuthority: 'accepted', candidate: false, origin: 'accepted' });
    expect(contradicts).toMatchObject({
      edgeAuthority: 'candidate',
      candidate: true,
      origin: 'model_proposed',
      scientific: true,
    });
    // The *node* is accepted evidence; only the relation is a proposal. Conflating the two
    // would show an unreviewed contradiction as accepted state.
    expect(contradicts.ref.authority).toBe('accepted');
  });

  it('renders exactly what the graph returned and never re-adds a pruned neighbour', () => {
    const everything = neighbourGroups(asNeighbourhood(neighboursClaim));
    const project = neighbourGroups(asNeighbourhood(neighboursProject));
    const ids = (list: typeof project) => list.flatMap((g) => g.neighbours.map((n) => n.ref.id));
    expect(ids(everything)).toContain('M0009');
    expect(ids(project)).not.toContain('M0009');
    expect(ids(project)).toContain('M0031');
  });
});

describe('provenance', () => {
  it('reads the path as origin then one step per hop, each labelled by its edge', () => {
    const path = provenancePathFrom(asProvenance(provenanceClaim));
    expect(path).not.toBeNull();
    expect(path!.steps.map((step) => [step.ref.id, step.relation ?? null])).toEqual([
      ['C0001', null],
      ['E0482', 'supports'],
      ['B0081', 'anchored_at'],
      ['A0017-3', 'contains'],
    ]);
  });

  it('reads the exact anchor off the last hop’s edge metadata', () => {
    expect(anchorFrom(asProvenance(provenanceClaim))).toMatchObject({
      artifactId: 'A0017-3',
      page: 6,
      block: 'B0081',
      span: { start: 418, end: 512 },
    });
  });

  it('says there is no path rather than inventing one', () => {
    expect(provenancePathFrom(asProvenance(provenanceNone))).toBeNull();
    expect(anchorFrom(asProvenance(provenanceNone))).toBeNull();
  });
});

describe('routeForResolvedLink', () => {
  it('opens an artifact at its exact page and block', () => {
    expect(
      routeForResolvedLink(link('rh://artifact/A0017-3?page=6&block=B0081'), asResolved(resolveArtifact)),
    ).toBe('/source/A0017-3?page=6&block=B0081');
  });

  it('sends a plain artifact link to its Work, which is where the file is listed', () => {
    expect(routeForResolvedLink(link('rh://artifact/A0017-3'), asResolved(resolveArtifact))).toBe(
      '/corpus/W0017',
    );
  });

  it('lands a session link on the message it names', () => {
    expect(routeForResolvedLink(link('rh://session/CS0001?message=M0042'), null)).toBe(
      '/?session=CS0001&message=M0042',
    );
  });

  it('opens the manuscript at the file and line', () => {
    expect(routeForResolvedLink(link('rh://manuscript/main.tex?line=120'), null)).toBe(
      '/manuscript?file=main.tex&line=120',
    );
  });

  it('takes an attachment to the session the graph says holds it', () => {
    const view = {
      ...asResolved(resolvePrivate),
      node: { ...asResolved(resolvePrivate).node!, id: 'SA0003', metadata: { session: 'CS0002' } },
    };
    expect(routeForResolvedLink(link('rh://attachment/SA0003'), view, { session: 'CS0001' })).toBe(
      '/?session=CS0002&attachment=SA0003',
    );
  });

  it('falls back to the session on screen when the graph names none', () => {
    expect(routeForResolvedLink(link('rh://attachment/SA0003'), null, { session: 'CS0001' })).toBe(
      '/?session=CS0001&attachment=SA0003',
    );
  });

  it('routes evidence, claims and questions to their own pages', () => {
    expect(routeForResolvedLink(link('rh://evidence/E0482'), null)).toBe('/evidence/E0482');
    expect(routeForResolvedLink(link('rh://claim/C0001'), null)).toBe('/claims/C0001');
    expect(routeForResolvedLink(link('rh://question/RQ0002'), null)).toBe('/questions');
  });
});

/**
 * The same links, opened in a window that is inside one project.
 *
 * A deep link addresses an object, never a URL, so the prefix is not part of the link and
 * is applied to the answer. What these pin is that the address survives it: the page and
 * block of a source link, the message of a session link, and the file and line of a
 * manuscript link are all still there after the route is pointed at the project.
 */
describe('routeForResolvedLink under a project prefix', () => {
  const inProject = (path: string) => projectHref('prj_abc', path);

  it('opens an artifact at the exact page and block, inside the project', () => {
    expect(
      routeForResolvedLink(
        link('rh://artifact/A0017-3?page=6&block=B0081'),
        asResolved(resolveArtifact),
        {},
        inProject,
      ),
    ).toBe('/projects/prj_abc/source/A0017-3?page=6&block=B0081');
  });

  it('lands a session link on the message it names, inside the project', () => {
    expect(routeForResolvedLink(link('rh://session/CS0001?message=M0042'), null, {}, inProject)).toBe(
      '/projects/prj_abc/?session=CS0001&message=M0042',
    );
  });

  it('opens the manuscript at the file and line, inside the project', () => {
    expect(routeForResolvedLink(link('rh://manuscript/main.tex?line=120'), null, {}, inProject)).toBe(
      '/projects/prj_abc/manuscript?file=main.tex&line=120',
    );
  });

  it('takes an attachment to its session, inside the project', () => {
    expect(
      routeForResolvedLink(link('rh://attachment/SA0003'), null, { session: 'CS0001' }, inProject),
    ).toBe('/projects/prj_abc/?session=CS0001&attachment=SA0003');
  });

  it('sends a plain artifact and an entity link through the same one prefix', () => {
    expect(
      routeForResolvedLink(link('rh://artifact/A0017-3'), asResolved(resolveArtifact), {}, inProject),
    ).toBe('/projects/prj_abc/corpus/W0017');
    expect(routeForResolvedLink(link('rh://claim/C0001'), null, {}, inProject)).toBe(
      '/projects/prj_abc/claims/C0001',
    );
  });
});

describe('graph chips under a project prefix', () => {
  const inProject = (path: string) => projectHref('prj_abc', path);

  it('points a projected node’s chip at the project it was read in', () => {
    const node = asNeighbourhood(neighboursClaim).neighbours[0]!.node;
    expect(refFromNode(node, { href: inProject }).href).toMatch(/^\/projects\/prj_abc\//);
    expect(refFromNode(node).href).not.toMatch(/^\/projects\//);
  });

  it('points every neighbour row at the project too', () => {
    const groups = neighbourGroups(asNeighbourhood(neighboursClaim), { href: inProject });
    const hrefs = groups
      .flatMap((group) => group.neighbours.map((neighbour) => neighbour.ref.href))
      .filter((href): href is string => href !== undefined);

    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.every((href) => href.startsWith('/projects/prj_abc/'))).toBe(true);
  });

  it('points every step of a provenance path at the project', () => {
    const path = provenancePathFrom(asProvenance(provenanceClaim), { href: inProject });
    const hrefs = (path?.steps ?? [])
      .map((step) => step.ref.href)
      .filter((href): href is string => href !== undefined);

    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.every((href) => href.startsWith('/projects/prj_abc/'))).toBe(true);
  });
});
