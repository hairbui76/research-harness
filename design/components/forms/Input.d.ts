import * as React from "react";

/**
 * Single-line text field with an uppercase mono label.
 * @startingPoint section="Forms" subtitle="Inputs, selects, checkboxes, radios and switches" viewport="700x340"
 */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  /** Helper copy under the field. */
  hint?: string;
  /** Error copy — also turns the border red. */
  error?: string;
  /** Lucide icon name shown inside the field. */
  iconLeft?: string;
  size?: "sm" | "md";
}

export declare function Input(props: InputProps): JSX.Element;
