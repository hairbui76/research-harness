import { useCallback, useRef, useState } from 'react';

export interface ControllableOptions<T> {
  /** When defined, the component is controlled and never keeps its own copy. */
  value?: T | undefined;
  /** Starting value for the uncontrolled case. */
  defaultValue: T;
  /** Called on every change, controlled or not. */
  onChange?: ((value: T) => void) | undefined;
}

/**
 * One state hook for both controlled and uncontrolled components.
 *
 * Returns the value in force and a setter that updates internal state only while the
 * component is uncontrolled, and always calls `onChange`. Switching between modes during
 * the lifetime of a component is a bug, so it warns once.
 */
export function useControllable<T>({
  value,
  defaultValue,
  onChange,
}: ControllableOptions<T>): [T, (next: T) => void] {
  const isControlled = value !== undefined;
  const [internal, setInternal] = useState<T>(defaultValue);
  const wasControlled = useRef(isControlled);

  if (wasControlled.current !== isControlled) {
    wasControlled.current = isControlled;
    console.warn(
      '[@research-harness/design] a component switched between controlled and uncontrolled. ' +
        'Pass a defined value for the whole lifetime, or none at all.',
    );
  }

  const set = useCallback(
    (next: T) => {
      if (!isControlled) setInternal(next);
      onChange?.(next);
    },
    [isControlled, onChange],
  );

  return [isControlled ? (value as T) : internal, set];
}
