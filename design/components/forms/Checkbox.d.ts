import * as React from "react";

export interface CheckboxProps {
  label?: React.ReactNode;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean, event: React.MouseEvent) => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export declare function Checkbox(props: CheckboxProps): JSX.Element;
