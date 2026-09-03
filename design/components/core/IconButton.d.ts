import * as React from "react";

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Lucide icon name. */
  name: string;
  size?: "sm" | "md" | "lg";
  variant?: "ghost" | "outlined" | "solid";
  /** Accessible label; falls back to the icon name. */
  label?: string;
}

export declare function IconButton(props: IconButtonProps): JSX.Element;
