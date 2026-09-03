import * as React from "react";

export interface IconProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Lucide icon name in kebab-case, e.g. "message-circle". */
  name: string;
  /** Square size in px. Default 20. */
  size?: number;
  /** Any CSS color; defaults to currentColor. */
  color?: string;
}

export declare function Icon(props: IconProps): JSX.Element;
