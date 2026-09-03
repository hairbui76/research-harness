/**
 * Appearance settings: the theme and the density.
 *
 * Both are Design System state — `ThemeProvider` owns them, writes them to `data-theme` /
 * `data-density` on the document element, and persists them under its own namespaced
 * `localStorage` key. Nothing here is research state, and nothing here is sent anywhere.
 */
import { Dialog, DialogBody, DialogHeader, Select, useTheme } from '@research-harness/design';
import type { Density, Theme } from '@research-harness/design';

export interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { theme, density, setTheme, setDensity } = useTheme();

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="sm">
      <DialogHeader>Settings</DialogHeader>
      <DialogBody>
        <div className="rh-web-stack rh-web-stack--tight">
          <Select
            label="Theme"
            description="Dark is the default. Both themes carry the same scientific states."
            value={theme}
            onChange={(event) => setTheme(event.target.value as Theme)}
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </Select>
          <Select
            label="Density"
            description="Compact tightens rows and tables for scanning long queues."
            value={density}
            onChange={(event) => setDensity(event.target.value as Density)}
          >
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </Select>
        </div>
      </DialogBody>
    </Dialog>
  );
}
