/**
 * The attachment mappers: renames, and the two places a rename is not enough.
 *
 * The daemon's `IdentityChoice` has five members and the Design System's has three, and
 * `undecided` is the one case where the researcher must answer. Those are the only
 * judgements in the file, so they are the ones worth pinning down: everything else is
 * asserted by being carried through unchanged.
 */
import { describe, expect, it } from 'vitest';
import { blockedReasonsOf, describePromotion, saveOptionsOf, toSendability } from './mappers';
import type {
  AttachmentIdentityView,
  AttachmentPromotionView,
  AttachmentSendCheck,
  AttachmentView,
} from '../../../api/dto';
import checkBlocked from '../../../test/fixtures/attachments/check-blocked.json';
import checkOk from '../../../test/fixtures/attachments/check-ok.json';
import identityDuplicate from '../../../test/fixtures/attachments/identity-duplicate.json';
import identityExistingWork from '../../../test/fixtures/attachments/identity-existing-work.json';
import promotionDuplicate from '../../../test/fixtures/attachments/promotion-duplicate.json';
import promotionVersion from '../../../test/fixtures/attachments/promotion-version.json';

const blocked = checkBlocked as AttachmentSendCheck;
const ok = checkOk as AttachmentSendCheck;

describe('blockedReasonsOf', () => {
  it('is empty when the daemon says the send may proceed', () => {
    expect(blockedReasonsOf(ok)).toEqual([]);
    expect(blockedReasonsOf(null)).toEqual([]);
  });

  it('names every blocked item, with the daemon’s reason and its suggestion', () => {
    const reasons = blockedReasonsOf(blocked);
    expect(reasons).toHaveLength(2);
    expect(reasons[0]).toEqual({
      attachmentId: 'SA0001',
      reason: 'figure-3-latency.png: local-small/text-1 does not accept image/png',
      suggestedModel: 'vendor-vision/vision-1',
    });
    // Every one of them, not just the first: a researcher must not fix one file, be
    // refused again, and fix the next (attachments design §5).
    expect(reasons[1]?.attachmentId).toBe('SA0002');
  });
});

describe('toSendability', () => {
  it('carries the verdict through without inventing one', () => {
    const item = blocked.items[0];
    if (item === undefined) throw new Error('the fixture has no items');
    expect(toSendability(item)).toEqual({
      ok: false,
      reason: 'local-small/text-1 does not accept image/png',
      suggestedModel: 'vendor-vision/vision-1',
    });
    const sent = ok.items[0];
    if (sent === undefined) throw new Error('the fixture has no items');
    expect(toSendability(sent)).toEqual({ ok: true });
  });
});

describe('saveOptionsOf', () => {
  it('offers one decided identity and sends no answer with it', () => {
    const options = saveOptionsOf(identityExistingWork as AttachmentIdentityView);
    expect(options).toHaveLength(1);
    expect(options[0]?.choice.kind).toBe('existing_work_new_version');
    expect(options[0]?.choice.work?.id).toBe('W0007');
    // The resolver decided; `save_to_corpus` resolves again under the workspace lock, so an
    // answer invented here could only disagree with it.
    expect(options[0]?.request).toEqual({});
  });

  it('names a duplicate as a duplicate', () => {
    const options = saveOptionsOf(identityDuplicate as AttachmentIdentityView);
    expect(options).toHaveLength(1);
    expect(options[0]?.choice.kind).toBe('existing_artifact');
    expect(options[0]?.choice.artifact?.id).toBe('A0007-3');
  });

  it('turns an undecided identity into the two answers the capability accepts', () => {
    const undecided: AttachmentIdentityView = {
      ...(identityExistingWork as AttachmentIdentityView),
      choice: 'undecided',
      outcome: 'unresolved',
      requires_confirmation: true,
      reasons: ['the title matches W0007 and W0011; nothing decides between them'],
    };
    const options = saveOptionsOf(undecided);
    expect(options.map((option) => option.request)).toEqual([
      { attach_to: 'W0007' },
      { as_new: true },
    ]);
    // Nothing is ranked or preselected here; the dialog asks (PRODUCT §13).
    expect(options.map((option) => option.choice.kind)).toEqual([
      'existing_work_new_version',
      'new_work',
    ]);
  });

  it('offers only a new work when the resolver matched nothing at all', () => {
    const distinct: AttachmentIdentityView = {
      ...(identityExistingWork as AttachmentIdentityView),
      choice: 'undecided',
      outcome: 'unresolved',
      requires_confirmation: true,
      work: null,
    };
    expect(saveOptionsOf(distinct).map((option) => option.request)).toEqual([{ as_new: true }]);
  });
});

describe('describePromotion', () => {
  it('says what was created and that no evidence was', () => {
    const sentence = describePromotion(promotionVersion as unknown as AttachmentPromotionView);
    expect(sentence).toContain('a new version V0007-2 of W0007, artifact A0007-3');
    expect(sentence).toContain('It was parsed into anchored blocks.');
    expect(sentence).toContain('No evidence was created');
  });

  it('says that saving the same bytes copied nothing', () => {
    const sentence = describePromotion(promotionDuplicate as unknown as AttachmentPromotionView);
    expect(sentence).toContain('already in the corpus');
    expect(sentence).toContain('A0007-3 was linked and nothing was copied');
    expect(sentence).toContain('It was not parsed.');
  });
});

describe('the attachment record shapes', () => {
  it('reads a promotion’s attachment as an in-corpus record with all three links', () => {
    const promotion = promotionVersion as unknown as AttachmentPromotionView;
    const record: AttachmentView = promotion.attachment;
    expect(record.state).toBe('in_corpus');
    expect([record.work, record.version, record.artifact]).toEqual([
      'W0007',
      'V0007-2',
      'A0007-3',
    ]);
  });
});
