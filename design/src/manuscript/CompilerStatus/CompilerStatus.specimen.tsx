import { CompilerStatus } from './CompilerStatus';
import { failedBuild, noToolchainBuild, succeededBuild } from '../manuscript.specimen-data';

export const title = 'CompilerStatus';

export const specimens = [
  {
    name: 'Succeeded',
    render: () => <CompilerStatus build={succeededBuild} onCompile={() => undefined} />,
  },
  {
    name: 'Running',
    render: () => (
      <CompilerStatus
        build={{ ...succeededBuild, status: 'running', finishedAt: undefined }}
        onStop={() => undefined}
      />
    ),
  },
  {
    name: 'Failed, with the last good PDF still on record',
    render: () => <CompilerStatus build={failedBuild} onCompile={() => undefined} />,
  },
  {
    name: 'Timed out',
    render: () => (
      <CompilerStatus
        build={{ ...failedBuild, status: 'timed_out' }}
        onCompile={() => undefined}
      />
    ),
  },
  {
    name: 'No toolchain',
    render: () => <CompilerStatus build={noToolchainBuild} />,
  },
];
