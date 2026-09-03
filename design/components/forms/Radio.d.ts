import * as React from "react";

export interface RadioProps {
  label?: React.ReactNode;
  name?: string;
  value?: string;
  checked?: boolean;
  onChange?: (event: React.ChangeEvent<HTMLInputElement>) => void;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export declare function Radio(props: RadioProps): JSX.Element;
