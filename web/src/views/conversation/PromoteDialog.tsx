/**
 * Promotion: the one path from a chat answer to reviewable research state.
 *
 * Four targets, and only four (conversation spec §6, `domain/conversation.py`): a research
 * note, a research question, a Claim *candidate*, a Decision *candidate*. Evidence is not
 * offered and the dialog says why on screen rather than leaving a gap — evidence needs an
 * artifact and an exact resolvable anchor, and prose has neither, so it is created through
 * the evidence capabilities from a source.
 *
 * Nothing here is accepted. `session.promote` copies the excerpt with provenance back to
 * the session and message, the original message is untouched, and a candidate enters the
 * existing review workflow. The dialog shows the provenance it is about to record, because
 * a promotion a researcher cannot trace is a promotion they cannot defend.
 *
 * A window the daemon resolved as an agent host may read this dialog and not submit it:
 * every promotion is `MUTATE`, and the reason is printed rather than inferred (ADR-007).
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Dialog,
  ErrorNotice,
  Input,
  PROMOTION_TARGETS,
  PROMOTION_TARGET_META,
  Select,
  Textarea,
  useToast,
} from '@research-harness/design';
import type { PromotionTarget } from '@research-harness/design';
import { CapabilityError } from '../../api/client';
import type { ConversationMessage, PromotionView } from '../../api/dto';
import { useSession } from '../../app/session';
import { useProjectPaths } from '../../app/projectPaths';
import { entityRefFor, routeForEntity } from './mappers';

export interface PromoteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  message: ConversationMessage | null;
  /** Which target the message's Promote menu chose. */
  target: PromotionTarget;
  /** The excerpt, when the researcher selected part of the message. */
  excerpt?: string;
}

/** The message's prose, blocks joined the way `Message.text()` joins them server-side. */
function proseOf(message: ConversationMessage | null): string {
  if (!message) return '';
  return message.blocks
    .filter((block): block is { kind: 'text'; text: string } => block.kind === 'text')
    .map((block) => block.text)
    .join('\n\n');
}

export function PromoteDialog({
  open,
  onOpenChange,
  message,
  target: initialTarget,
  excerpt,
}: PromoteDialogProps) {
  const { client, canMutate, mutationBlockedReason } = useSession();
  const { href } = useProjectPaths();
  const { toast } = useToast();
  const navigate = useNavigate();

  const [target, setTarget] = useState<PromotionTarget>(initialTarget);
  const [text, setText] = useState('');
  const [rationale, setRationale] = useState('');
  const [subject, setSubject] = useState('');
  const [predicate, setPredicate] = useState('');
  const [object, setObject] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Reopening on a different message starts from that message, not from the last one.
  useEffect(() => {
    if (!open) return;
    setTarget(initialTarget);
    setText(excerpt && excerpt.trim().length > 0 ? excerpt : proseOf(message));
    setRationale('');
    setSubject('');
    setPredicate('');
    setObject('');
    setTitle('');
    setError(null);
  }, [excerpt, initialTarget, message, open]);

  if (!message) return null;

  const claimForm = target === 'claim_candidate';
  const decisionForm = target === 'decision_candidate';
  const incompleteClaim =
    claimForm && (subject.trim() === '' || predicate.trim() === '' || object.trim() === '');

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const result: PromotionView = await client.promoteMessage({
        session: message.session,
        message: message.id,
        target,
        excerpt: text,
        ...(rationale.trim() ? { rationale: rationale.trim() } : {}),
        ...(claimForm
          ? {
              subject: subject.trim(),
              predicate: predicate.trim(),
              object: object.trim(),
            }
          : {}),
        ...(decisionForm && title.trim() ? { title: title.trim() } : {}),
      });
      onOpenChange(false);
      announce(result);
    } catch (cause) {
      setError(cause instanceof CapabilityError ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const announce = (result: PromotionView): void => {
    const created = result.object_id ?? result.note_key ?? null;
    const route = created ? routeForEntity(entityRefFor(created).kind, created, {}, href) : null;
    toast({
      title: `${PROMOTION_TARGET_META[result.target].label} created${created ? `: ${created}` : ''}`,
      // `review` is the daemon's sentence about what still has to happen to it.
      description: result.review || 'It enters review; nothing was accepted.',
      tone: 'success',
      ...(route ? { action: { label: `Open ${created}`, onClick: () => navigate(route) } } : {}),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="md">
      <Dialog.Header>Promote this message</Dialog.Header>
      <Dialog.Body>
        <div className="rh-web-stack rh-web-stack--tight">
          <p className="rh-text-secondary">
            Promotion copies. {message.id} stays in the transcript exactly as it is, and what
            this creates carries provenance back to it.
          </p>

          <Select
            label="Promote to"
            value={target}
            onChange={(event) => setTarget(event.target.value as PromotionTarget)}
          >
            {PROMOTION_TARGETS.map((option) => (
              <option key={option} value={option}>
                {PROMOTION_TARGET_META[option].label}
              </option>
            ))}
          </Select>
          <p className="rh-text-secondary">{PROMOTION_TARGET_META[target].description}</p>

          {/*
            Evidence is absent from the list above, and saying nothing about it would read
            as an oversight. The rule is the product's, not this screen's (spec §6).

            `urgent={false}`: this is true before the dialog opens and stays true, so it is
            a condition rather than an event. Announcing it assertively would interrupt a
            screen-reader user with the same rule every time they open the dialog, and the
            one notice here that is genuinely news — the daemon refusing the promotion they
            just asked for — would then arrive in the same tone as boilerplate.
          */}
          <ErrorNotice
            kind="blocked"
            urgent={false}
            title="Evidence cannot be promoted from prose"
            description={
              'Evidence needs an artifact and an exact, resolvable source anchor. Open the ' +
              'source in the corpus and accept the span there instead.'
            }
            safety={{ source: 'safe' }}
          />

          <Textarea
            label="Excerpt"
            rows={5}
            value={text}
            description="Copied from the message exactly as written."
            onChange={(event) => setText(event.target.value)}
          />

          {claimForm ? (
            <>
              <Input
                label="Subject"
                value={subject}
                description="What the claim is about, e.g. batching."
                onChange={(event) => setSubject(event.target.value)}
              />
              <Input
                label="Predicate"
                value={predicate}
                description="What it does, e.g. reduces."
                onChange={(event) => setPredicate(event.target.value)}
              />
              <Input
                label="Object"
                value={object}
                description="What it acts on, e.g. tail latency."
                onChange={(event) => setObject(event.target.value)}
              />
            </>
          ) : null}

          {decisionForm ? (
            <Input
              label="Title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          ) : null}

          <Textarea
            label="Rationale"
            rows={3}
            value={rationale}
            description="Why this is worth reviewing. Optional."
            onChange={(event) => setRationale(event.target.value)}
          />

          <dl className="rh-web-fields">
            <div className="rh-web-field">
              <dt className="rh-text-label">Provenance</dt>
              <dd>
                <code>{message.session}</code> · <code>{message.id}</code> ·{' '}
                {new Date(message.created_at).toISOString()}
              </dd>
            </div>
          </dl>

          {/* This one *is* an event: it answers the press the researcher just made, so it
              keeps `fatal`'s assertive announcement. */}
          {error !== null ? (
            <ErrorNotice
              kind="fatal"
              title="The daemon refused this promotion"
              description={error}
              safety={{ draft: 'safe', source: 'safe' }}
            />
          ) : null}
          {/* Already on screen when the dialog opens, for the same reason as the evidence
              rule above: it describes what this window is, not what just happened. */}
          {!canMutate && mutationBlockedReason ? (
            <ErrorNotice
              kind="blocked"
              urgent={false}
              title="This window may not promote"
              description={mutationBlockedReason}
              safety={{ draft: 'safe', source: 'safe' }}
            />
          ) : null}
        </div>
      </Dialog.Body>
      <Dialog.Footer>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={busy}
          loadingLabel="Promoting"
          disabled={!canMutate || busy || text.trim() === '' || incompleteClaim}
          onClick={() => void submit()}
        >
          Promote
        </Button>
      </Dialog.Footer>
    </Dialog>
  );
}
