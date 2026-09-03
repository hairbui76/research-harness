import * as React from "react";

export interface SwitchProps {
  label?: React.ReactNode;
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export declare function Switch(props: SwitchProps): JSX.Element;
