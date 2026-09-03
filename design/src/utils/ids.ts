import { useId } from 'react';

/**
 * Use the caller's id when it gave one, otherwise a generated one.
 *
 * React 18's `useId` contains colons, which are legal in an `id` attribute but awkward in
 * a CSS or test selector, so they are stripped and the id is prefixed with the component
 * it belongs to. Prefixes are single words (`rh-input`, `rh-radiogroup`) so the snapshot
 * helper can normalise them.
 */
export function useAutoId(provided?: string, prefix = 'rh'): string {
  const generated = useId();
  return provided ?? `${prefix}-${generated.replace(/:/g, '')}`;
}

/**
 * Join the ids that are actually present into one `aria-describedby` value, or `undefined`
 * when there is nothing to point at. An empty `aria-describedby` is an accessibility bug,
 * so this never returns an empty string.
 */
export function joinIds(...ids: (string | false | null | undefined)[]): string | undefined {
  const present = ids.filter((id): id is string => typeof id === 'string' && id.length > 0);
  return present.length > 0 ? present.join(' ') : undefined;
}

export interface FieldIds {
  /** id of the control itself */
  controlId: string;
  /** id of the description paragraph, when a description is rendered */
  descriptionId: string;
  /** id of the error paragraph, when an error is rendered */
  errorId: string;
}

/** The three ids a labelled form control needs, derived from one base. */
export function useFieldIds(provided?: string, prefix = 'rh-field'): FieldIds {
  const controlId = useAutoId(provided, prefix);
  return {
    controlId,
    descriptionId: `${controlId}-description`,
    errorId: `${controlId}-error`,
  };
}
