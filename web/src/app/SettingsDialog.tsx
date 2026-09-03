/**
 * Settings: appearance, and the providers this project may route to.
 *
 * Appearance is Design System state — `ThemeProvider` owns the theme and the density,
 * writes them to `data-theme` / `data-density` on the document element, and persists them
 * under its own namespaced `localStorage` key. Nothing there is research state, and
 * nothing there is sent anywhere.
 *
 * Models & providers is the other kind entirely: it reads and writes the project's
 * provider configuration through the daemon. It decides nothing itself — every state word
 * on that screen is one the daemon sent (spec §18).
 */
import {
  Dialog,
  DialogBody,
  DialogHeader,
  Select,
  Tab,
  TabList,
  TabPanel,
  Tabs,
  useTheme,
} from '@research-harness/design';
import type { Density, Theme } from '@research-harness/design';
import { ProvidersSettings } from './settings/ProvidersSettings';

export interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { theme, density, setTheme, setDensity } = useTheme();

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg">
      <DialogHeader>Settings</DialogHeader>
      <DialogBody>
        {/* `manual`: the providers panel scans on mount, so arrowing past a tab must not
            start a scan the researcher did not ask for. */}
        <Tabs defaultValue="appearance" activation="manual">
          <TabList aria-label="Settings sections">
            <Tab value="appearance">Appearance</Tab>
            <Tab value="providers">Models &amp; providers</Tab>
          </TabList>
          <TabPanel value="appearance">
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
          </TabPanel>
          <TabPanel value="providers">
            <ProvidersSettings />
          </TabPanel>
        </Tabs>
      </DialogBody>
    </Dialog>
  );
}
