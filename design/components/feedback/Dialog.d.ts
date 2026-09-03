import * as React from "react";

export interface DialogProps extends React.HTMLAttributes<HTMLDivElement> {
  open?: boolean;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Buttons, right-aligned. */
  footer?: React.ReactNode;
  onClose?: () => void;
  /** Panel width in px. Default 440. */
  width?: number;
  children?: React.ReactNode;
}

export declare function Dialog(props: DialogProps): JSX.Element;
