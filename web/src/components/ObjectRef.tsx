/**
 * A reference to a research object, as a link the cockpit can follow.
 *
 * `EntityRef` is the Design System's presentation of a stable `@`-reference: the kind's
 * glyph, the id, the authority it holds and whether it resolved. It has no router, so the
 * cockpit gives it the route as an `href` — a real link, middle-clickable and readable by
 * assistive technology — and turns a plain click into a client-side navigation.
 *
 * Resolution is `resolved` here because these ids came out of the daemon's own listings:
 * the object exists and this window may read it. When W3 wires `graph.resolve`, an
 * unresolved or private reference passes its real state through instead.
 */
import { useNavigate } from 'react-router-dom';
import { EntityRef } from '@research-harness/design';
import type { AuthorityLabel, EntityKind, EntityRefSize, ResolutionState } from '@research-harness/design';

export interface ObjectRefProps {
  id: string;
  kind: EntityKind;
  /** Cockpit route this reference opens. */
  to: string;
  label?: string;
  authority?: AuthorityLabel;
  resolution?: ResolutionState;
  size?: EntityRefSize;
  /** Attach the kind/resolution tooltip. Off inside dense tables and lists. */
  describe?: boolean;
}

export function ObjectRef({
  id,
  kind,
  to,
  label,
  authority,
  resolution = 'resolved',
  size = 'sm',
  describe = false,
}: ObjectRefProps) {
  const navigate = useNavigate();
  return (
    <EntityRef
      size={size}
      describe={describe}
      entity={{
        id,
        kind,
        resolution,
        href: to,
        ...(label === undefined ? {} : { label }),
        ...(authority === undefined ? {} : { authority }),
      }}
      onOpen={() => navigate(to)}
    />
  );
}
