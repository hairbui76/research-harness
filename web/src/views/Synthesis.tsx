/**
 * Synthesis: one field across the corpus, as a table.
 *
 * `synthesis.compare` reads an existing matrix; it proposes no new facts. An empty cell
 * means "not recorded", never "the work lacks the property" — the table says so, because
 * reading absence out of a blank cell is exactly the mistake PRODUCT §11 is about.
 */
import { useState } from 'react';
import { Button, FullPageWorkspace, Input } from '@research-harness/design';
import type { JsonObject } from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
} from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

export function SynthesisPage() {
  const { client } = useSession();
  const [field, setField] = useState('');
  const [requested, setRequested] = useState<string | null>(null);

  const matrices = useAsync(() => client.index(), [client]);
  const comparison = useAsync(
    async () => (requested ? client.compareField(requested) : null),
    [client, requested],
  );

  if (matrices.loading) return <Loading what="the synthesis matrices" />;
  if (matrices.error) return <ErrorBox error={matrices.error} retry={matrices.reload} />;

  const built = matrices.data?.matrices ?? [];
  return (
    <FullPageWorkspace
      title="Synthesis"
      description="A matrix reads what was recorded; it proposes no new facts."
    >
      <div className="rh-web-stack">
        {built.length === 0 ? (
          <Empty>No synthesis matrix has been built.</Empty>
        ) : (
          built.map((matrix) => (
            <Panel
              key={matrix.id}
              title={matrix.name}
              action={matrix.stale === 'stale' ? <StatusBadge status="stale" /> : null}
            >
              <Fields>
                <Field label="Id">
                  <code>{matrix.id}</code>
                </Field>
                <Field label="Taxonomy">{matrix.taxonomy ?? '—'}</Field>
                <Field label="Rows">{matrix.works} works</Field>
                <Field label="Fields">{matrix.fields.join(', ') || '—'}</Field>
                <Field label="Cells">{matrix.cells}</Field>
              </Fields>
            </Panel>
          ))
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
              fieldClassName="rh-web-inline-field"
              onChange={(event) => setField(event.target.value)}
            />
            <Button type="submit" variant="primary" size="sm" disabled={!field.trim()}>
              Compare
            </Button>
          </form>

          {requested && comparison.loading ? <Loading what={requested} /> : null}
          {comparison.error ? <ErrorBox error={comparison.error} /> : null}
          {comparison.data ? <ComparisonTable rows={comparison.data.rows} /> : null}
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}

export function ComparisonTable({ rows }: { rows: JsonObject[] }) {
  if (rows.length === 0) return <Empty>No rows for that field.</Empty>;
  const columns = Object.keys(rows[0] ?? {});
  return (
    <>
      <DataTable
        label="Field comparison"
        head={
          <tr>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {column}
              </th>
            ))}
          </tr>
        }
      >
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column}>{format(row[column])}</td>
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

function format(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
