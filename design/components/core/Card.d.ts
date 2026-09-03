import * as React from "react";

/**
 * Warm-cream container with an oat hairline and 8px radius — no shadow.
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  tone?: "cream" | "white" | "inverse";
  /** Inner padding in px. Default 24. */
  padding?: number;
  /** Adds a border-darkening hover state. */
  interactive?: boolean;
  children?: React.ReactNode;
}

export declare function Card(props: CardProps): JSX.Element;
