import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import {
  AsyncState,
  Badge,
  Button,
  Card,
  Checkbox,
  Combobox,
  Dialog,
  ErrorNotice,
  Icon,
  ICON_NAMES,
  IconButton,
  Input,
  Menu,
  Pane,
  PaneGroup,
  PaneHandle,
  Popover,
  Progress,
  Radio,
  RadioGroup,
  ResearchState,
  ScrollArea,
  Select,
  Skeleton,
  STATUS_NAMES,
  Switch,
  Tab,
  TabList,
  TabPanel,
  Tabs,
  Tag,
  Textarea,
  ToastProvider,
  Tooltip,
  VirtualList,
  useToast,
} from '../src/index';

/**
 * The primitives DS1a and DS1b built, in the states a reviewer needs to see.
 *
 * It lives in `specimens/` rather than beside each primitive because those folders belong
 * to the engineers who wrote them; `main.tsx` globs this directory as well as `src/`.
 */

function Row({ children }: { children: ReactNode }): ReactElement {
  return <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>{children}</div>;
}

function Block({ children }: { children: ReactNode }): ReactElement {
  return <div className="gallery-block">{children}</div>;
}

function ToastDemo(): ReactElement {
  const toast = useToast();
  return (
    <Button
      onClick={() =>
        toast.toast({
          title: 'Context pack CP0007 assembled',
          description: '9 items included, 2 omitted for the token budget.',
          tone: 'info',
        })
      }
    >
      Show a toast
    </Button>
  );
}

function DialogDemo(): ReactElement {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="danger" onClick={() => setOpen(true)}>
        Discard the draft
      </Button>
      <Dialog open={open} onOpenChange={setOpen} role="alertdialog" size="sm">
        <Dialog.Header>Discard this draft?</Dialog.Header>
        <Dialog.Body>The message has not been sent. Discarding it cannot be undone.</Dialog.Body>
        <Dialog.Footer>
          <Dialog.Close className="rh-button rh-button--secondary rh-button--md">Keep it</Dialog.Close>
          <Button variant="danger" onClick={() => setOpen(false)}>
            Discard
          </Button>
        </Dialog.Footer>
      </Dialog>
    </>
  );
}

const virtualItems = Array.from({ length: 500 }, (_unused, index) => ({
  id: `M${String(index).padStart(4, '0')}`,
  text: `Message ${index} in a long transcript`,
}));

export const title = 'Primitives (DS1a, DS1b)';

export const specimens = [
  {
    name: 'Button — variants, sizes, loading, disabled',
    render: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Row>
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="accent" iconStart="send">
            Send
          </Button>
        </Row>
        <Row>
          <Button size="sm">Small</Button>
          <Button size="sm" iconStart="plus">
            New session
          </Button>
          <Button loading>Compiling</Button>
          <Button disabled>Disabled</Button>
          <Button iconEnd="arrow-right">Next</Button>
        </Row>
      </div>
    ),
  },
  {
    name: 'IconButton',
    render: () => (
      <Row>
        <IconButton icon="settings" label="Settings" />
        <IconButton icon="trash-2" label="Delete" variant="danger" />
        <IconButton icon="send" label="Send" variant="accent" />
        <IconButton icon="refresh-cw" label="Retry" loading />
        <IconButton icon="x" label="Close" size="sm" />
      </Row>
    ),
  },
  {
    name: 'Badge — the six scientific states, plus feedback tones',
    render: () => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Row>
          {STATUS_NAMES.map((status) => (
            <Badge key={status} status={status} />
          ))}
        </Row>
        <Row>
          <Badge tone="neutral">Neutral</Badge>
          <Badge tone="success" icon="circle-check">
            Compiled
          </Badge>
          <Badge tone="error" icon="alert-circle">
            Failed
          </Badge>
          <Badge tone="warning" icon="alert-triangle">
            Degraded
          </Badge>
          <Badge tone="info" icon="info">
            Info
          </Badge>
          <Badge tone="accent" icon="sparkles">
            Model activity
          </Badge>
        </Row>
      </div>
    ),
  },
  {
    name: 'Tag — selectable and removable',
    render: () => (
      <Row>
        <Tag icon="at-sign">E0482</Tag>
        <Tag icon="at-sign" defaultSelected onSelect={() => undefined}>
          C0041
        </Tag>
        <Tag icon="paperclip" onRemove={() => undefined}>
          survey.pdf
        </Tag>
        <Tag icon="tag" disabled onSelect={() => undefined}>
          Disabled
        </Tag>
      </Row>
    ),
  },
  {
    name: 'Card — surfaces',
    render: () => (
      <Row>
        <Card header={<strong>Raised</strong>} style={{ inlineSize: 220 }}>
          Menus, popovers and dialogs sit on this.
        </Card>
        <Card surface="pane" header={<strong>Pane</strong>} style={{ inlineSize: 220 }}>
          A working pane on the canvas.
        </Card>
        <Card surface="paper" header={<strong>Paper</strong>} style={{ inlineSize: 220 }}>
          A page of a source: near-white in both themes, with its own ink.
        </Card>
      </Row>
    ),
  },
  {
    name: 'Form controls — default, described, error, disabled',
    render: () => (
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', inlineSize: '100%' }}>
        <Input label="Session title" defaultValue="Thermal tolerance" />
        <Input label="Search" iconStart="search" placeholder="Find a claim" />
        <Input label="Entry file" error="No such file under manuscript/." defaultValue="main.text" />
        <Input label="Read-only host" disabled defaultValue="/mnt/readonly" />
        <Textarea label="Message" description="Shift+Enter for a new line" rows={3} />
        <Select label="Model" defaultValue="local">
          <option value="local">Local — llama3.1:8b</option>
          <option value="remote">Remote — claude-sonnet</option>
        </Select>
        <Checkbox label="Include prior sessions" defaultChecked />
        <Switch label="Send attachments to the provider" />
        <RadioGroup label="Egress" defaultValue="project">
          <Radio value="private" label="Private — never leaves the machine" />
          <Radio value="project" label="Project — may reach the provider" />
        </RadioGroup>
      </div>
    ),
  },
  {
    name: 'Tabs — automatic and manual activation',
    render: () => (
      <Block>
        <Tabs defaultValue="context">
          <TabList aria-label="Inspector">
            <Tab value="context">Context</Tab>
            <Tab value="evidence">Evidence</Tab>
            <Tab value="claims" disabled>
              Claims
            </Tab>
          </TabList>
          <TabPanel value="context">The context pack for the last model call.</TabPanel>
          <TabPanel value="evidence">Accepted evidence for this selection.</TabPanel>
          <TabPanel value="claims">Claims.</TabPanel>
        </Tabs>
      </Block>
    ),
  },
  {
    name: 'Overlays — Tooltip, Popover, Menu, Combobox, Dialog, Toast',
    render: () => (
      <Row>
        <Tooltip content="Compiles with the local toolchain">
          <Button iconStart="play">Compile</Button>
        </Tooltip>
        <Popover>
          <Popover.Trigger>Context used</Popover.Trigger>
          <Popover.Content aria-label="Context used">
            9 items included, 2 omitted for the token budget.
          </Popover.Content>
        </Popover>
        <Menu>
          <Menu.Trigger className="rh-button rh-button--secondary rh-button--md">Actions</Menu.Trigger>
          <Menu.Content aria-label="Actions">
            <Menu.Item icon={<Icon name="pen-line" size={14} />}>Rename</Menu.Item>
            <Menu.Item icon={<Icon name="copy" size={14} />} hint="Ctrl+C">
              Copy id
            </Menu.Item>
            <Menu.Separator />
            <Menu.Item icon={<Icon name="trash-2" size={14} />}>Delete</Menu.Item>
          </Menu.Content>
        </Menu>
        <Combobox
          label="Reference"
          items={[
            { id: 'E0482', label: 'E0482 — thermal maxima table' },
            { id: 'C0041', label: 'C0041 — tolerance rises with acclimation' },
            { id: 'W0017', label: 'W0017 — Smith 2024' },
          ]}
        />
        <DialogDemo />
        <ToastProvider>
          <ToastDemo />
        </ToastProvider>
      </Row>
    ),
  },
  {
    name: 'Progress and Skeleton',
    render: () => (
      <Block>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Progress label="Compiling the manuscript" indeterminate showValue />
          <Progress label="Indexing the corpus" value={64} showValue />
          <Progress label="Quiet" value={30} size="sm" tone="neutral" />
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <Skeleton shape="circle" width={32} height={32} />
            <Skeleton shape="text" lines={3} width={280} />
            <Skeleton shape="block" width={120} height={64} />
          </div>
        </div>
      </Block>
    ),
  },
  {
    name: 'ScrollArea, PaneGroup and VirtualList',
    render: () => (
      <Block>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ScrollArea label="A long note" maxHeight={120} scrollable>
            <p style={{ margin: 0 }}>
              {Array.from({ length: 12 }, (_unused, index) => `Paragraph ${index + 1}. `).join('')}
            </p>
          </ScrollArea>

          <div className="gallery-frame-fixed" style={{ blockSize: '10rem' }}>
            <PaneGroup direction="horizontal" defaultSizes={[30, 70]}>
              <Pane minSize={15} style={{ padding: 12 }}>
                Left pane
              </Pane>
              <PaneHandle label="Resize the panes" />
              <Pane minSize={20} style={{ padding: 12 }}>
                Right pane — drag the handle, or focus it and use the arrow keys.
              </Pane>
            </PaneGroup>
          </div>

          <div className="gallery-frame-fixed" style={{ blockSize: '12rem' }}>
            <VirtualList
              label="A long transcript"
              items={virtualItems}
              itemKey={(item) => item.id}
              height="12rem"
              estimatedItemHeight={32}
              renderItem={(item) => (
                <div style={{ padding: '6px 12px' }}>
                  <code>{item.id}</code> {item.text}
                </div>
              )}
            />
          </div>
        </div>
      </Block>
    ),
  },
  {
    name: 'Async and research states',
    render: () => (
      <Block>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <AsyncState kind="loading" title="Assembling the context pack" progress={{}} />
          <AsyncState kind="empty" title="No sessions yet" description="Start one to begin." />
          <AsyncState
            kind="stale"
            title="This anchor moved"
            description="A0017-3 was re-parsed after this evidence was recorded."
            safety={{ source: 'at-risk' }}
            actions={[{ label: 'Re-anchor', onClick: () => undefined, iconStart: 'link' }]}
          />
          <AsyncState
            kind="retryable"
            title="The provider did not answer"
            safety={{ draft: 'safe' }}
            actions={[{ label: 'Retry', onClick: () => undefined, iconStart: 'refresh-cw' }]}
          />
          <ErrorNotice
            kind="fatal"
            title="The build could not start"
            detail="latexmk: command not found (exit 127)"
            actions={[{ label: 'Open setup guidance', onClick: () => undefined }]}
            onDismiss={() => undefined}
          />
          <ResearchState state={{ case: 'provider-unavailable', provider: 'Local Ollama' }} />
          <ResearchState state={{ case: 'egress-blocked', policy: 'private-only' }} />
          <ResearchState state={{ case: 'anchor-stale', anchor: 'A0017-3' }} />
        </div>
      </Block>
    ),
  },
  {
    name: 'Icon registry',
    render: () => (
      <Row>
        {ICON_NAMES.map((name) => (
          <span
            key={name}
            title={name}
            style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4, inlineSize: 84 }}
          >
            <Icon name={name} size={20} />
            <code style={{ fontSize: 10 }}>{name}</code>
          </span>
        ))}
      </Row>
    ),
  },
];
