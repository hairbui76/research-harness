/**
 * Synthesis: what the matrices cannot say yet, then the matrices themselves.
 *
 * A matrix reads one property across works and proposes nothing. An empty cell means
 * "not recorded", never "the work lacks the property", and novelty is never inferred from
 * one (PRODUCT §7.1, §33) — which is exactly why this page now opens with the gaps. A page
 * that showed only the cells it has would let a reader take the shape of the table for the
 * shape of the field; a page that names the readings nobody has taken cannot.
 *
 * The matrix stays a table, because a table is what a matrix is: one property read down a
 * column across works, which is the only thing a table does better than a sentence. What
 * left the card-wrapped-table template is everything around it — the coverage of each
 * matrix is a sentence rather than a row of counts, and the gaps are groups of sentences.
 *
 * Every gap sentence here is the daemon's and every one of them is about the record. None
 * of them is about a work, and nothing on this page proposes anything.
 *
 * The frame is mounted before the read resolves, and so is the compare form: a field can be
 * compared while the matrix list is still arriving, or after it failed.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, FullPageWorkspace, Input, humaniseTerm } from '@research-harness/design';
import type { JsonObject, MatrixView, ResearchGroup } from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
  fieldLabel,
} from '../components/Feedback';
import { readable } from './EvidenceReview';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './synthesis.css';

export function SynthesisPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const [field, setField] = useState('');
  const [requested, setRequested] = useState<string | null>(null);

  const synthesis = useAsync(() => client.synthesis(), [client]);
  const comparison = useAsync(
    async () => (requested ? client.compareField(requested) : null),
    [client, requested],
  );

  const report = synthesis.data;
  const matrices = report?.matrices ?? [];
  return (
    <FullPageWorkspace
      busy={synthesis.loading}
      title="Synthesis"
      description={report?.summary ?? 'A matrix reads what was recorded; it proposes no new facts.'}
    >
      <div className="rh-web-stack">
        {synthesis.loading ? (
          <Loading what="the synthesis matrices" shape="cards" />
        ) : synthesis.error ? (
          <ErrorBox error={synthesis.error} retry={synthesis.reload} />
        ) : matrices.length === 0 ? (
          <Empty
            description="A matrix lines the works of the corpus up against the fields that were recorded for them, so one property can be read across all of them at once. It is built from accepted evidence; there is nothing for it to read yet."
            action={<Link to={href('/corpus')}>See the works a matrix would read</Link>}
          >
            No synthesis matrix has been built yet
          </Empty>
        ) : (
          <>
            <Panel title="What these matrices cannot say yet">
              {report!.gaps.length > 0 ? (
                report!.gaps.map((group, index) => (
                  // The rule under every gap is one rule, so it is stated once rather than
                  // once per matrix.
                  <MatrixGaps key={group.key} group={group} explain={index === 0} />
                ))
              ) : (
                <Empty
                  flat
                  description="A matrix reads one property across works, from accepted evidence. A reading nobody has recorded is a gap in the record; there is none left in these matrices."
                  action={<Link to={href('/corpus')}>See the works these matrices read</Link>}
                >
                  Every reading these matrices declare has been recorded
                </Empty>
              )}
            </Panel>
            {matrices.map((matrix) => (
              <MatrixPanel key={matrix.id} matrix={matrix} />
            ))}
          </>
        )}

        <Panel title="Compare a field">
          <form
            className="rh-web-row"
            onSubmit={(event) => {
              event.preventDefault();
              if (field.trim()) setRequested(field.trim());
            }}
          >
            <Input
              id="compare-field"
              label="Field"
              value={field}
              placeholder="tokenization"
              fieldClassName="rh-web-synthesis__field"
              onChange={(event) => setField(event.target.value)}
            />
            <Button type="submit" variant="primary" size="sm" disabled={!field.trim()}>
              Compare
            </Button>
          </form>

          {requested && comparison.loading ? <Loading what={requested} shape="table" /> : null}
          {comparison.error ? (
            <ErrorBox error={comparison.error} retry={comparison.reload} />
          ) : null}
          {comparison.data ? (
            <ComparisonTable rows={comparison.data.rows} {...(requested ? { field: requested } : {})} />
          ) : null}
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}

/**
 * One matrix's gaps: the columns with no reading, and the works it has no row for.
 *
 * A column is named once with how much of it is unread rather than once per empty cell —
 * a column nobody has read is one gap in the record, not one per work. A work with no row
 * links to itself, because the corpus does hold it; a field links nowhere, because there is
 * no screen for a column of a matrix and a link back to this page is not a next step.
 */
function MatrixGaps({ group, explain }: { group: ResearchGroup; explain: boolean }) {
  const { href } = useProjectPaths();
  return (
    <div className="rh-web-synthesis__group">
      <p className="rh-web-row">
        {group.title} — {group.summary}
      </p>
      {explain ? <p className="rh-web-synthesis__detail">{group.detail}</p> : null}
      <ul className="rh-web-list rh-web-list--tight rh-web-synthesis__items">
        {group.items.map((item) => (
          <li key={item.id}>
            {item.route ? (
              <Link to={href(item.route)}>
                <code>{item.label}</code>
              </Link>
            ) : (
              <span className="rh-web-synthesis__column">{fieldLabel(item.label)}</span>
            )}{' '}
            <span className="rh-text-secondary">— {item.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One matrix, stated in the daemon's own sentences.
 *
 * Its shape and its coverage used to be a row of counts, one of which — `Cells` — was a
 * bare number a reader had to divide by another to learn anything. Both are sentences the
 * daemon composes, and both are about the record rather than about the corpus.
 */
function MatrixPanel({ matrix }: { matrix: MatrixView }) {
  return (
    <Panel
      title={matrix.name}
      action={
        matrix.stale === 'stale' ? (
          <StatusBadge status="stale" vocabulary="staleState" describe />
        ) : null
      }
    >
      <Fields>
        <Field label="Id">
          <code>{matrix.id}</code>
        </Field>
        <Field label="Taxonomy">{matrix.taxonomy || 'None — the labels are the matrix’s own'}</Field>
        <Field label="Reads">{matrix.shape}</Field>
        <Field label="Recorded">{matrix.coverage}</Field>
        <Field label="Fields">{matrix.fields.map(fieldLabel).join(', ') || 'None recorded'}</Field>
      </Fields>
    </Panel>
  );
}

export function ComparisonTable({ rows, field }: { rows: JsonObject[]; field?: string }) {
  if (rows.length === 0) {
    return (
      <Empty
        flat
        description="No matrix has a value recorded under that name. That is a gap in what has been recorded, not a statement about the works — check the field's spelling against a matrix above."
      >
        {field ? `Nothing recorded under “${field}”` : 'Nothing recorded under that field'}
      </Empty>
    );
  }
  const columns = Object.keys(rows[0] ?? {});
  return (
    <>
      <DataTable
        label="Field comparison"
        head={
          <tr>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {humaniseTerm(column)}
              </th>
            ))}
          </tr>
        }
      >
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column}>{readable(row[column])}</td>
            ))}
          </tr>
        ))}
      </DataTable>
      <p className="rh-text-secondary">
        An empty cell means &ldquo;not recorded&rdquo;, never &ldquo;absent&rdquo;.
      </p>
    </>
  );
}
