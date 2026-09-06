/**
 * Models & providers: the two kinds of provider this project can route to.
 *
 * They are separate tabs because they are separate things. A local CLI is a subscription
 * login on this workstation that the daemon detects, and the researcher configures here;
 * an API provider is a key in the environment, which the browser never touches.
 */
import { useState } from 'react';
import { Tab, TabList, TabPanel, Tabs } from '@research-harness/design';
import { useSession } from '../session';
import { ApiProvidersTab } from './ApiProvidersTab';
import { LocalCliTab } from './LocalCliTab';
import './settings.css';

export function ProvidersSettings() {
  const { client, canMutate, mutationBlockedReason } = useSession();
  // Each tab is mounted the first time it is opened and kept from then on. A runtime card
  // holds the entry name, model, reasoning and priority the researcher is part-way through
  // typing; looking at the API providers list and coming back must not discard it.
  const [opened, setOpened] = useState<readonly string[]>(['local']);
  return (
    <Tabs
      defaultValue="local"
      activation="manual"
      onValueChange={(value) =>
        setOpened((seen) => (seen.includes(value) ? seen : [...seen, value]))
      }
    >
      <TabList aria-label="Provider kinds">
        <Tab value="local">Local CLIs</Tab>
        <Tab value="api">API providers</Tab>
      </TabList>
      <TabPanel value="local" keepMounted>
        <LocalCliTab
          client={client}
          canMutate={canMutate}
          mutationBlockedReason={mutationBlockedReason}
        />
      </TabPanel>
      <TabPanel value="api" keepMounted={opened.includes('api')}>
        <ApiProvidersTab client={client} />
      </TabPanel>
    </Tabs>
  );
}
