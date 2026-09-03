import * as React from "react";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: "neutral" | "accent" | "success" | "error" | "info" | "inverse";
  children?: React.ReactNode;
}

export declare function Badge(props: BadgeProps): JSX.Element;
