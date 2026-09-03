import * as React from "react";

export interface TagProps extends React.HTMLAttributes<HTMLSpanElement> {
  selected?: boolean;
  /** Shows a dismiss affordance when provided. */
  onRemove?: () => void;
  children?: React.ReactNode;
}

export declare function Tag(props: TagProps): JSX.Element;
