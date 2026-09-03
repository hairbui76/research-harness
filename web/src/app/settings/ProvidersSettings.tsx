/**
 * Models & providers: the two kinds of provider this project can route to.
 *
 * They are separate tabs because they are separate things. A local CLI is a subscription
 * login on this workstation that the daemon detects, and the researcher configures here;
 * an API provider is a key in the environment, which the browser never touches.
 */
import { Tab, TabList, TabPanel, Tabs } from '@research-harness/design';
import { useSession } from '../session';
import { ApiProvidersTab } from './ApiProvidersTab';
import { LocalCliTab } from './LocalCliTab';
import './settings.css';

export function ProvidersSettings() {
  const { client, canMutate, mutationBlockedReason } = useSession();
  return (
    <Tabs defaultValue="local" activation="manual">
      <TabList aria-label="Provider kinds">
        <Tab value="local">Local CLIs</Tab>
        <Tab value="api">API providers</Tab>
      </TabList>
      <TabPanel value="local">
        <LocalCliTab
          client={client}
          canMutate={canMutate}
          mutationBlockedReason={mutationBlockedReason}
        />
      </TabPanel>
      <TabPanel value="api">
        <ApiProvidersTab client={client} />
      </TabPanel>
    </Tabs>
  );
}
