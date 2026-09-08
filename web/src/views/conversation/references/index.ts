/**
 * Graph-backed references: completion, resolution, deep links and traversal.
 *
 * Task W3 of the v1.1 plan and the Web half of Phase 20. Everything the conversation
 * workspace needs from the ResearchGraph enters through this directory:
 *
 * | file | what it owns |
 * |---|---|
 * | `graphReferenceProvider.ts` | `@` completion over `graph.autocomplete`, with W1's index provider behind it and `graph.status` deciding which answers |
 * | `useResolveReferences.ts` | every composer token resolved against canonical state before it is sent |
 * | `deepLinks.ts` | `rh://` links resolved before anything navigates |
 * | `useNeighbourhood.ts` / `useProvenance.ts` | one-hop traversal, and the path to the exact source anchor |
 * | `mappers.ts` | `graph.*` responses → Design System view models, deciding nothing |
 * | `ContextTab.tsx` / `ReferenceDetails.tsx` | the inspector's graph pane |
 * | `GraphStatusNote.tsx` / `ReferenceMarks.tsx` / `DeepLinkNotice.tsx` | the three things the researcher has to be told |
 * | `ArtifactSourceRoute.tsx` | `/source/:artifactId`, where an artifact deep link lands |
 */
import './references.css';

export { ArtifactSourcePage } from './ArtifactSourceRoute';
export { GraphContextPanel } from './ContextTab';
export { DeepLinkNotice } from './DeepLinkNotice';
export { GraphStatusNote, useIndexNoteRead } from './GraphStatusNote';
export { ReferenceMarks } from './ReferenceMarks';
export { ReferenceDetails } from './ReferenceDetails';
export { followable, routeForResolvedLink, useDeepLinks, MANUSCRIPT_PATH, SOURCE_PATH } from './deepLinks';
export type { DeepLinkApi, DeepLinkContext, DeepLinkProblem } from './deepLinks';
export { graphReferenceProvider, useGraphReferences } from './graphReferenceProvider';
export type { GraphDegradation, GraphReferenceOptions, GraphReferencesApi } from './graphReferenceProvider';
export {
  anchorFrom,
  entityKindOfNodeKind,
  headingFor,
  neighbourGroups,
  neighbourModel,
  provenancePathFrom,
  refFromNode,
  refFromResolved,
  resolutionOf,
  RELATION_HEADINGS,
} from './mappers';
export type { NeighbourGroup, NeighbourModel, NodeRefOptions } from './mappers';
export { traversalVisibility, useNeighbourhood } from './useNeighbourhood';
export type { NeighbourhoodApi, NeighbourhoodOptions } from './useNeighbourhood';
export { useProvenance } from './useProvenance';
export type { ProvenanceApi, ProvenanceOptions } from './useProvenance';
export { useResolveReferences } from './useResolveReferences';
export type {
  ResolveReferencesApi,
  ResolveReferencesOptions,
  ResolvedReference,
} from './useResolveReferences';
