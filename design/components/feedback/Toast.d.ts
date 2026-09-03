import * as React from "react";

/**
 * Transient off-black notification.
 * @startingPoint section="Feedback" subtitle="Toasts, tooltips and dialogs" viewport="700x320"
 */
export interface ToastProps extends React.HTMLAttributes<HTMLDivElement> {
  title: React.ReactNode;
  description?: React.ReactNode;
  tone?: "neutral" | "success" | "error" | "info";
  onDismiss?: () => void;
}

export declare function Toast(props: ToastProps): JSX.Element;
