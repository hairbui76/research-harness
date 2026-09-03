import {
  Children,
  cloneElement,
  forwardRef,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
} from 'react';
import type {
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  ReactElement,
  ReactNode,
} from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { useId } from '../../hooks/useId';
import { cx } from '../../utils/cx';

export type PaneDirection = 'horizontal' | 'vertical';

interface PaneConstraint {
  min: number;
  max: number;
  collapsible: boolean;
  collapsedSize: number;
}

/** Internal wiring passed from PaneGroup to its children. Not part of the public API. */
interface InternalPaneState {
  __rhSize?: number;
  __rhDirection?: PaneDirection;
  __rhCollapsed?: boolean;
  __rhPaneId?: string;
}

interface InternalHandleState {
  __rhDirection?: PaneDirection;
  __rhValue?: number;
  __rhMin?: number;
  __rhMax?: number;
  __rhControls?: string;
  __rhCollapsible?: boolean;
  __rhCollapsed?: boolean;
  __rhOnKeyResize?: (deltaPercent: number) => void;
  __rhOnEdge?: (edge: 'min' | 'max') => void;
  __rhOnToggleCollapse?: () => void;
  __rhOnDragStart?: (clientX: number, clientY: number) => void;
}

export interface PaneProps extends HTMLAttributes<HTMLDivElement>, InternalPaneState {
  /** Smallest size as a percentage of the group. Default 10. */
  minSize?: number;
  /** Largest size as a percentage of the group. Default 100. */
  maxSize?: number;
  /** Initial size as a percentage; the group splits the remainder evenly otherwise. */
  defaultSize?: number;
  /** The neighbouring handle can collapse this pane with Enter, Home or a drag. */
  collapsible?: boolean;
  /** Size when collapsed, as a percentage. Default 0. */
  collapsedSize?: number;
  /** Called when the pane crosses into or out of its collapsed size. */
  onCollapsedChange?: (collapsed: boolean) => void;
  children?: ReactNode;
}

export const Pane = forwardRef<HTMLDivElement, PaneProps>(function Pane(
  {
    minSize,
    maxSize,
    defaultSize,
    collapsible = false,
    collapsedSize,
    onCollapsedChange,
    __rhSize = 0,
    __rhDirection = 'horizontal',
    __rhCollapsed = false,
    __rhPaneId,
    className,
    style,
    children,
    ...rest
  },
  ref,
) {
  const previousCollapsed = useRef(__rhCollapsed);
  useEffect(() => {
    if (previousCollapsed.current === __rhCollapsed) return;
    previousCollapsed.current = __rhCollapsed;
    onCollapsedChange?.(__rhCollapsed);
  }, [__rhCollapsed, onCollapsedChange]);

  // The constraints are consumed by PaneGroup, which reads them off this element's props.
  // They are mirrored onto the DOM so the layout contract is visible to CSS and to tests
  // rather than hidden inside React.
  return (
    <div
      ref={ref}
      id={__rhPaneId}
      className={cx('rh-pane', className)}
      data-collapsed={__rhCollapsed ? '' : undefined}
      data-collapsible={collapsible ? '' : undefined}
      data-min-size={minSize}
      data-max-size={maxSize}
      data-default-size={defaultSize}
      data-collapsed-size={collapsedSize}
      style={{ ...style, flexBasis: `${__rhSize}%` }}
      data-direction={__rhDirection}
      {...rest}
    >
      {children}
    </div>
  );
});

export interface PaneHandleProps
  extends Omit<HTMLAttributes<HTMLDivElement>, 'onDragStart'>,
    InternalHandleState {
  /** Accessible name, e.g. "Resize the research inspector". */
  label?: string;
  /** Percentage moved per arrow key. Default 2. */
  step?: number;
  /** Percentage moved per Shift+arrow. Default 10. */
  largeStep?: number;
  disabled?: boolean;
}

export const PaneHandle = forwardRef<HTMLDivElement, PaneHandleProps>(function PaneHandle(
  {
    label = 'Resize panes',
    step = 2,
    largeStep = 10,
    disabled = false,
    __rhDirection = 'horizontal',
    __rhValue = 50,
    __rhMin = 0,
    __rhMax = 100,
    __rhControls,
    __rhCollapsible = false,
    __rhCollapsed = false,
    __rhOnKeyResize,
    __rhOnEdge,
    __rhOnToggleCollapse,
    __rhOnDragStart,
    className,
    onKeyDown,
    onMouseDown,
    onTouchStart,
    ...rest
  },
  ref,
) {
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
    onKeyDown?.(event);
    if (event.defaultPrevented || disabled) return;
    const amount = event.shiftKey ? largeStep : step;
    const decrease = __rhDirection === 'horizontal' ? 'ArrowLeft' : 'ArrowUp';
    const increase = __rhDirection === 'horizontal' ? 'ArrowRight' : 'ArrowDown';

    switch (event.key) {
      case decrease:
        event.preventDefault();
        __rhOnKeyResize?.(-amount);
        return;
      case increase:
        event.preventDefault();
        __rhOnKeyResize?.(amount);
        return;
      case 'Home':
        event.preventDefault();
        __rhOnEdge?.('min');
        return;
      case 'End':
        event.preventDefault();
        __rhOnEdge?.('max');
        return;
      case 'Enter':
        if (!__rhCollapsible) return;
        event.preventDefault();
        __rhOnToggleCollapse?.();
        return;
      default:
    }
  };

  return (
    <div
      ref={ref}
      role="separator"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-orientation={__rhDirection === 'horizontal' ? 'vertical' : 'horizontal'}
      aria-valuenow={Math.round(__rhValue)}
      aria-valuemin={Math.round(__rhMin)}
      aria-valuemax={Math.round(__rhMax)}
      aria-controls={__rhControls}
      aria-disabled={disabled ? true : undefined}
      data-direction={__rhDirection}
      data-collapsed={__rhCollapsed ? '' : undefined}
      className={cx('rh-pane-handle', className)}
      onKeyDown={handleKeyDown}
      onMouseDown={(event) => {
        onMouseDown?.(event);
        if (disabled || event.defaultPrevented) return;
        event.preventDefault();
        __rhOnDragStart?.(event.clientX, event.clientY);
      }}
      onTouchStart={(event) => {
        onTouchStart?.(event);
        if (disabled || event.defaultPrevented) return;
        const touch = event.touches[0];
        if (touch) __rhOnDragStart?.(touch.clientX, touch.clientY);
      }}
      {...rest}
    >
      <span className="rh-pane-handle__grip" aria-hidden="true" />
    </div>
  );
});

export interface PaneGroupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** `horizontal` lays panes out side by side; `vertical` stacks them. */
  direction?: PaneDirection;
  /** Controlled sizes as percentages, one per Pane. */
  sizes?: number[];
  defaultSizes?: number[];
  /** Called on every layout change - drag, keyboard resize or collapse. */
  onLayoutChange?: (sizes: number[]) => void;
  children?: ReactNode;
}

function normaliseSizes(requested: Array<number | undefined>, count: number): number[] {
  if (count === 0) return [];
  const known = requested.slice(0, count);
  const specified = known.filter((size): size is number => typeof size === 'number');
  const specifiedTotal = specified.reduce((total, size) => total + size, 0);
  const remaining = Math.max(0, 100 - specifiedTotal);
  const unspecifiedCount = count - specified.length;
  const each = unspecifiedCount > 0 ? remaining / unspecifiedCount : 0;
  const filled = Array.from({ length: count }, (_unused, index) =>
    typeof known[index] === 'number' ? (known[index] as number) : each,
  );
  const total = filled.reduce((sum, size) => sum + size, 0);
  if (total <= 0) return Array.from({ length: count }, () => 100 / count);
  return filled.map((size) => (size / total) * 100);
}

function snapCollapse(size: number, constraint: PaneConstraint): number {
  if (!constraint.collapsible) return size;
  if (size <= constraint.collapsedSize || size >= constraint.min) return size;
  const midpoint = (constraint.collapsedSize + constraint.min) / 2;
  return size < midpoint ? constraint.collapsedSize : constraint.min;
}

/** Moves `delta` percent across the boundary between pane `index` and `index + 1`. */
export function resizeAt(
  sizes: readonly number[],
  index: number,
  delta: number,
  constraints: readonly PaneConstraint[],
): number[] {
  const first = sizes[index];
  const second = sizes[index + 1];
  const firstConstraint = constraints[index];
  const secondConstraint = constraints[index + 1];
  if (
    first === undefined ||
    second === undefined ||
    firstConstraint === undefined ||
    secondConstraint === undefined
  ) {
    return [...sizes];
  }

  const firstLower = firstConstraint.collapsible ? firstConstraint.collapsedSize : firstConstraint.min;
  const secondLower = secondConstraint.collapsible
    ? secondConstraint.collapsedSize
    : secondConstraint.min;

  let bounded = delta;
  bounded = Math.min(bounded, firstConstraint.max - first);
  bounded = Math.max(bounded, firstLower - first);
  bounded = Math.min(bounded, second - secondLower);
  bounded = Math.max(bounded, second - secondConstraint.max);

  const pairTotal = first + second;
  let nextFirst = snapCollapse(first + bounded, firstConstraint);
  let nextSecond = pairTotal - nextFirst;
  const snappedSecond = snapCollapse(nextSecond, secondConstraint);
  if (snappedSecond !== nextSecond) {
    nextSecond = snappedSecond;
    nextFirst = pairTotal - nextSecond;
  }

  const result = [...sizes];
  result[index] = nextFirst;
  result[index + 1] = nextSecond;
  return result;
}

/**
 * The three-pane workspace and the manuscript editor/preview split. Sizes are percentages
 * of the group, so a layout survives a window resize. Every handle is a `separator` that
 * reports its position, moves with the arrow keys, jumps to its limits with Home and End
 * and collapses with Enter - a pane can always be resized without a pointer.
 */
export const PaneGroup = forwardRef<HTMLDivElement, PaneGroupProps>(function PaneGroup(
  { direction = 'horizontal', sizes, defaultSizes, onLayoutChange, className, children, id, ...rest },
  ref,
) {
  const groupRef = useRef<HTMLDivElement | null>(null);
  const groupId = useId(id, 'rh-panegroup');

  const items = useMemo(
    () => Children.toArray(children).filter((child): child is ReactElement => isValidElement(child)),
    [children],
  );
  const paneItems = useMemo(() => items.filter((item) => item.type === Pane), [items]);
  const paneProps = useMemo(() => paneItems.map((item) => item.props as PaneProps), [paneItems]);
  const count = paneProps.length;

  const constraints = useMemo<PaneConstraint[]>(
    () =>
      paneProps.map((props) => ({
        min: props.minSize ?? 10,
        max: props.maxSize ?? 100,
        collapsible: props.collapsible === true,
        collapsedSize: props.collapsedSize ?? 0,
      })),
    [paneProps],
  );

  const initialSizes = useMemo(
    () => normaliseSizes(defaultSizes ?? paneProps.map((props) => props.defaultSize), count),
    [count, defaultSizes, paneProps],
  );

  const [currentSizes, setSizes] = useControllableState<number[]>({
    value: sizes,
    defaultValue: initialSizes,
    onChange: onLayoutChange,
  });

  const sizesRef = useRef(currentSizes);
  sizesRef.current = currentSizes;
  const lastExpanded = useRef<number[]>([...initialSizes]);

  const applyDelta = useCallback(
    (handleIndex: number, delta: number): void => {
      const next = resizeAt(sizesRef.current, handleIndex, delta, constraints);
      next.forEach((size, index) => {
        const constraint = constraints[index];
        if (constraint && size > constraint.collapsedSize) lastExpanded.current[index] = size;
      });
      setSizes(next);
    },
    [constraints, setSizes],
  );

  const dragState = useRef<{ handleIndex: number; start: number; sizes: number[] } | null>(null);

  const beginDrag = useCallback(
    (handleIndex: number, clientX: number, clientY: number): void => {
      const group = groupRef.current;
      if (!group) return;
      const rect = group.getBoundingClientRect();
      const extent = direction === 'horizontal' ? rect.width : rect.height;
      if (extent <= 0) return; // No layout (SSR/jsdom): keyboard resizing still works.
      dragState.current = {
        handleIndex,
        start: direction === 'horizontal' ? clientX : clientY,
        sizes: [...sizesRef.current],
      };

      const move = (position: number): void => {
        const state = dragState.current;
        if (!state) return;
        const deltaPercent = ((position - state.start) / extent) * 100;
        const next = resizeAt(state.sizes, state.handleIndex, deltaPercent, constraints);
        next.forEach((size, index) => {
          const constraint = constraints[index];
          if (constraint && size > constraint.collapsedSize) lastExpanded.current[index] = size;
        });
        setSizes(next);
      };

      const onMouseMove = (event: MouseEvent): void =>
        move(direction === 'horizontal' ? event.clientX : event.clientY);
      const onTouchMove = (event: TouchEvent): void => {
        const touch = event.touches[0];
        if (touch) move(direction === 'horizontal' ? touch.clientX : touch.clientY);
      };
      const stop = (): void => {
        dragState.current = null;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', stop);
        document.removeEventListener('touchmove', onTouchMove);
        document.removeEventListener('touchend', stop);
        document.body.removeAttribute('data-rh-resizing');
      };

      document.body.setAttribute('data-rh-resizing', direction);
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', stop);
      document.addEventListener('touchmove', onTouchMove);
      document.addEventListener('touchend', stop);
    },
    [constraints, direction, setSizes],
  );

  useEffect(
    () => () => {
      if (typeof document !== 'undefined') document.body.removeAttribute('data-rh-resizing');
    },
    [],
  );

  const toEdge = useCallback(
    (handleIndex: number, edge: 'min' | 'max'): void => {
      const constraint = constraints[handleIndex];
      const size = sizesRef.current[handleIndex];
      if (!constraint || size === undefined) return;
      const target =
        edge === 'min' ? (constraint.collapsible ? constraint.collapsedSize : constraint.min) : constraint.max;
      applyDelta(handleIndex, target - size);
    },
    [applyDelta, constraints],
  );

  const toggleCollapse = useCallback(
    (handleIndex: number): void => {
      const constraint = constraints[handleIndex];
      const size = sizesRef.current[handleIndex];
      if (!constraint || size === undefined) return;
      const collapsed = size <= constraint.collapsedSize + 0.01;
      const restore = Math.max(lastExpanded.current[handleIndex] ?? constraint.min, constraint.min);
      applyDelta(handleIndex, collapsed ? restore - size : constraint.collapsedSize - size);
    },
    [applyDelta, constraints],
  );

  let paneCursor = -1;
  let handleCursor = -1;
  const rendered = items.map((item) => {
    if (item.type === Pane) {
      paneCursor += 1;
      const paneIndex = paneCursor;
      const constraint = constraints[paneIndex];
      const size = currentSizes[paneIndex] ?? 0;
      const props = item.props as PaneProps;
      return cloneElement(item as ReactElement<PaneProps>, {
        key: item.key ?? `pane-${paneIndex}`,
        __rhSize: size,
        __rhDirection: direction,
        __rhCollapsed: constraint ? size <= constraint.collapsedSize + 0.01 : false,
        __rhPaneId: props.id ?? `${groupId}-pane-${paneIndex}`,
      });
    }
    if (item.type === PaneHandle) {
      handleCursor += 1;
      const handleIndex = handleCursor;
      const constraint = constraints[handleIndex];
      const size = currentSizes[handleIndex] ?? 0;
      const paneItem = paneItems[handleIndex];
      const paneOwnId = paneItem ? (paneItem.props as PaneProps).id : undefined;
      return cloneElement(item as ReactElement<PaneHandleProps>, {
        key: item.key ?? `handle-${handleIndex}`,
        __rhDirection: direction,
        __rhValue: size,
        __rhMin: constraint?.collapsible ? constraint.collapsedSize : (constraint?.min ?? 0),
        __rhMax: constraint?.max ?? 100,
        __rhControls: paneOwnId ?? `${groupId}-pane-${handleIndex}`,
        __rhCollapsible: constraint?.collapsible ?? false,
        __rhCollapsed: constraint ? size <= constraint.collapsedSize + 0.01 : false,
        __rhOnKeyResize: (delta: number) => applyDelta(handleIndex, delta),
        __rhOnEdge: (edge: 'min' | 'max') => toEdge(handleIndex, edge),
        __rhOnToggleCollapse: () => toggleCollapse(handleIndex),
        __rhOnDragStart: (clientX: number, clientY: number) =>
          beginDrag(handleIndex, clientX, clientY),
      });
    }
    return item;
  });

  return (
    <div
      ref={(node) => {
        groupRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      id={groupId}
      className={cx('rh-pane-group', className)}
      data-direction={direction}
      {...rest}
    >
      {rendered}
    </div>
  );
});
