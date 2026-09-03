import * as React from "react";

export interface TooltipProps extends React.HTMLAttributes<HTMLSpanElement> {
  content: React.ReactNode;
  placement?: "top" | "bottom";
  children?: React.ReactNode;
}

export declare function Tooltip(props: TooltipProps): JSX.Element;
