import * as React from "react";

/**
 * Sharp 4px-radius button with scale(1.1) hover and scale(0.85) press.
 * @startingPoint section="Core" subtitle="Buttons, icon buttons, badges and tags" viewport="700x260"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary = off-black fill; outlined = hairline; warm = cream card button; accent = Fin Orange; ghost = bare. */
  variant?: "primary" | "outlined" | "warm" | "accent" | "ghost";
  size?: "sm" | "md" | "lg";
  fullWidth?: boolean;
  /** Renders an <a> instead of a <button>. */
  href?: string;
  children?: React.ReactNode;
}

export declare function Button(props: ButtonProps): JSX.Element;
