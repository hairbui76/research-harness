import * as React from "react";

export interface SelectOption { value: string; label: string }

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options?: Array<string | SelectOption>;
  size?: "sm" | "md";
}

export declare function Select(props: SelectProps): JSX.Element;
