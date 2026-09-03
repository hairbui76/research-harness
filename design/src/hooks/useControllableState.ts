import { useCallback, useRef, useState } from 'react';

export interface UseControllableStateOptions<T> {
  /** Controlled value. When defined on the first render the hook never owns the state. */
  value?: T | undefined;
  /** Initial value for the uncontrolled case. */
  defaultValue: T;
  /** Called for every change, controlled or not. */
  onChange?: ((value: T) => void) | undefined;
}

export type SetControllableState<T> = (next: T | ((previous: T) => T)) => void;

/**
 * One state hook for the controlled + uncontrolled contract that every primitive with a
 * `value` or `open` prop honours. Controlled-ness is latched on the first render so a
 * component never silently switches modes mid-life.
 */
export function useControllableState<T>({
  value,
  defaultValue,
  onChange,
}: UseControllableStateOptions<T>): [T, SetControllableState<T>] {
  const isControlled = useRef(value !== undefined).current;
  const [uncontrolled, setUncontrolled] = useState<T>(defaultValue);

  const uncontrolledRef = useRef(uncontrolled);
  uncontrolledRef.current = uncontrolled;
  const controlledRef = useRef(value);
  controlledRef.current = value;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const current = isControlled ? (value as T) : uncontrolled;

  const setValue = useCallback<SetControllableState<T>>(
    (next) => {
      const previous = isControlled ? (controlledRef.current as T) : uncontrolledRef.current;
      const resolved =
        typeof next === 'function' ? (next as (previous: T) => T)(previous) : next;
      if (!isControlled) setUncontrolled(resolved);
      if (!Object.is(resolved, previous)) onChangeRef.current?.(resolved);
    },
    [isControlled],
  );

  return [current, setValue];
}
