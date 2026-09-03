import * as React from "react";

export interface TabItem { value: string; label: string; count?: number }

/**
 * Underlined tab row for switching views.
 * @startingPoint section="Navigation" subtitle="Tab row with counts" viewport="700x140"
 */
export interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  items: Array<string | TabItem>;
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
}

export declare function Tabs(props: TabsProps): JSX.Element;
