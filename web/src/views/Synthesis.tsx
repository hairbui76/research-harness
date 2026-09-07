/**
 * Synthesis: what the matrices cannot say yet, then the matrices themselves, drawn.
 *
 * A matrix reads one property across works and proposes nothing. An empty cell means
 * "not recorded", never "the work lacks the property", and novelty is never inferred from
 * one (PRODUCT §7.1, §33) — which is why this page still opens with the gaps. A page that
 * showed only the cells it has would let a reader take the shape of the table for the shape
 * of the field; a page that names the readings nobody has taken cannot.
 *
 * What changed is the matrix itself. It used to be a definition list — Id, Taxonomy, Reads,
 * Recorded, Fields — which is the shape of the stored record, not the shape of the question
 * a researcher brings: how does this property vary across the works, which of them has no
 * reading for it, what does a reading rest on, and where do two of them read differently.
 * None of those is answerable from a list of field names, and the compare form used to ask
 * the researcher to type back a field name printed two lines above it.
 *
 * So the matrix is drawn as the instrument it is: works down the rows, its declared fields
 * across the columns, every cell either the recorded reading or the words "Not recorded",
 * and every recorded cell openable onto the accepted spans it rests on. The field is picked
 * from the matrix's own columns — in the picker, or by pressing the column head — and the
 * column it names is marked in place rather than answered underneath. The grid takes the
 * full width and scrolls inside its own named region; the sentences stay at the measure.
 *
 * Nothing on this page is composed here. Which cell belongs where, which order the rows and
 * columns are read in, how much of a column is recorded and which labels are on record for
 * how many works are all the daemon's (`GET /synthesis`), for the reason every research page
 * follows: a client that decided any of it could disagree with the record (PRODUCT §5 P10).
 */
import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';
import { Combobox, FullPageWorkspace, humaniseResearchTokens } from '@research-harness/design';
import type { ComboboxItem } from '@research-harness/design';
import type { MatrixCellView, MatrixView, ResearchGroup } from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Loading,
  Panel,
  StatusBadge,
  fieldLabel,
} from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './synthesis.css';

export function SynthesisPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();

  const synthesis = useAsync(() => client.synthesis(), [client]);

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
          <Loading what="the synthesis matrices" shape="table" />
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
            {matrices.map((matrix, index) => (
              <MatrixPanel key={matrix.id} matrix={matrix} explain={index === 0} />
            ))}
          </>
        )}
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

/** Which cell of a grid is open, in one key. */
function cellKey(work: string, field: string): string {
  return `${work}::${field}`;
}

/**
 * One matrix: what it lines up, said in the daemon's sentences, and then drawn.
 *
 * `explain` puts the rule an empty cell stands for on the page once, under the first grid.
 * Saying it under every one of them would be the same sentence three times, and the gap
 * panel above has already said it for the readings nobody has taken.
 */
function MatrixPanel({ matrix, explain }: { matrix: MatrixView; explain: boolean }) {
  const [marked, setMarked] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);

  const column = matrix.columns.find((entry) => entry.field === marked) ?? null;
  return (
    <Panel
      title={matrix.name}
      action={
        <span className="rh-web-row">
          <code className="rh-web-object-id">{matrix.id}</code>
          {matrix.stale === 'stale' ? (
            <StatusBadge status="stale" vocabulary="staleState" describe />
          ) : null}
        </span>
      }
    >
      <p className="rh-web-synthesis__lead">
        {matrix.shape}. {matrix.coverage}.
      </p>
      <p className="rh-web-synthesis__lead rh-text-secondary">{matrix.labels_from}</p>
      <FieldPicker matrix={matrix} marked={marked} onMark={setMarked} />
      <MatrixGrid
        matrix={matrix}
        marked={marked}
        opened={opened}
        onMark={setMarked}
        onOpen={setOpened}
      />
      <p className="rh-web-synthesis__reading" role="status">
        {column ? `${fieldLabel(column.field)} — ${column.reading}` : ''}
      </p>
      {explain ? (
        <p className="rh-web-synthesis__detail">
          An empty cell means &ldquo;not recorded&rdquo;, never &ldquo;absent&rdquo;. Press a
          recorded cell to read the accepted evidence behind it, or a column head to read that
          field down the works.
        </p>
      ) : null}
    </Panel>
  );
}

/**
 * Pick the field to read down its column, out of the matrix's own columns.
 *
 * This was a text box the researcher typed a field name into — a name printed two panels
 * above it — and a wrong one came back as an empty table that reads uncomfortably like an
 * absence. A field belongs to a matrix, so the matrix offers its own; the same precedent
 * the claim screen's evidence picker set. The column heads pick too, for a grid narrow
 * enough to see all of at once; this is for the one that is not.
 */
function FieldPicker({
  matrix,
  marked,
  onMark,
}: {
  matrix: MatrixView;
  marked: string | null;
  onMark: (field: string | null) => void;
}) {
  const [query, setQuery] = useState('');
  const id = `matrix-field-${matrix.id}`;
  const wanted = query.trim().toLowerCase();
  const items: ComboboxItem<string>[] = matrix.columns
    .filter(
      (column) =>
        wanted === '' ||
        `${fieldLabel(column.field)} ${column.field}`.toLowerCase().includes(wanted),
    )
    .map((column) => ({
      id: column.field,
      label: fieldLabel(column.field),
      description: column.coverage,
      value: column.field,
    }));

  return (
    <div className="rh-web-stack rh-web-stack--tight rh-web-synthesis__picker">
      <label className="rh-field__label" id={`${id}-label`} htmlFor={id}>
        Read a field down its column
      </label>
      <Combobox
        id={id}
        aria-labelledby={`${id}-label`}
        label="Read a field down its column"
        placeholder="Every field this matrix declares"
        items={items}
        openOnFocus
        emptyMessage="This matrix declares no field under that name."
        query={query}
        onQueryChange={setQuery}
        value={marked}
        onChange={(item) => onMark(item?.value ?? null)}
      />
    </div>
  );
}

/**
 * The matrix, drawn: the works it declares down the rows, the fields across the columns.
 *
 * Every declared field gets a column and every declared work a row, including the ones
 * nobody has read: a grid that quietly dropped its unread columns would show a smaller
 * matrix than the project built. A cell nobody has read says "Not recorded" in words —
 * never a tint, never a dash, never an empty box a reader is left to interpret.
 */
function MatrixGrid({
  matrix,
  marked,
  opened,
  onMark,
  onOpen,
}: {
  matrix: MatrixView;
  marked: string | null;
  opened: string | null;
  onMark: (field: string | null) => void;
  onOpen: (key: string | null) => void;
}) {
  const { href } = useProjectPaths();
  const detailId = `matrix-cell-${matrix.id}`;
  return (
    <div className="rh-web-matrix">
      <DataTable
        label={`The ${matrix.name} matrix`}
        head={
          <tr>
            <th scope="col" className="rh-web-matrix__corner">
              Work
            </th>
            {matrix.columns.map((column) => (
              <th
                scope="col"
                key={column.field}
                data-marked={column.field === marked ? 'true' : undefined}
                {...(column.field === marked ? { 'aria-current': 'true' as const } : {})}
              >
                <button
                  type="button"
                  className="rh-web-matrix__head"
                  aria-pressed={column.field === marked}
                  onClick={() => onMark(column.field === marked ? null : column.field)}
                >
                  {fieldLabel(column.field)}
                </button>
              </th>
            ))}
          </tr>
        }
      >
        {matrix.rows.map((row) => {
          const open = row.cells.find((cell) => cellKey(cell.work, cell.field) === opened) ?? null;
          return (
            <Fragment key={row.work}>
              <tr>
                <th scope="row">
                  {row.route ? (
                    <Link to={href(row.route)}>{row.title || row.work}</Link>
                  ) : (
                    (row.title || row.work)
                  )}{' '}
                  <code className="rh-web-object-id">{row.work}</code>
                  <span className="rh-web-matrix__row-summary">{row.summary}</span>
                </th>
                {row.cells.map((cell) => {
                  const key = cellKey(cell.work, cell.field);
                  return (
                    <td
                      key={cell.field}
                      data-marked={cell.field === marked ? 'true' : undefined}
                      data-state={cell.recorded ? 'recorded' : 'not-recorded'}
                    >
                      <button
                        type="button"
                        className="rh-web-matrix__cell"
                        aria-expanded={key === opened}
                        {...(key === opened ? { 'aria-controls': detailId } : {})}
                        onClick={() => onOpen(key === opened ? null : key)}
                      >
                        {cell.recorded ? (
                          <>
                            <span className="rh-web-matrix__reading">{cell.reading}</span>
                            {cell.measurement ? (
                              <span className="rh-web-matrix__measure">{cell.measurement}</span>
                            ) : null}
                          </>
                        ) : (
                          <span className="rh-web-matrix__blank">Not recorded</span>
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
              {open ? (
                <tr className="rh-web-matrix__detail">
                  <td colSpan={matrix.columns.length + 1} id={detailId}>
                    <CellEvidence cell={open} />
                  </td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </DataTable>
    </div>
  );
}

/**
 * What one cell rests on: the daemon's sentence about the cell, then the spans themselves.
 *
 * A span is quoted exactly as it was accepted. A cell that cites evidence this workspace no
 * longer holds says which id it cannot reach rather than showing an empty quotation, and a
 * reading with no evidence behind it says that too — both are facts about the record, and
 * neither is drawn as an alarm.
 *
 * A span repeats its measured value only when the cell above is not already showing it: one
 * number on screen twice is one account too many, and the second one reads as a second
 * reading. The span is named the way every other surface names it (`AttentionName`), so the
 * field inside that name is spelled in words rather than as the identifier it is stored as.
 */
function CellEvidence({ cell }: { cell: MatrixCellView }) {
  const { href } = useProjectPaths();
  return (
    <div className="rh-web-stack rh-web-stack--tight rh-web-matrix__opened">
      <p className="rh-text-secondary">{cell.detail}</p>
      {cell.evidence.length > 0 ? (
        <ul className="rh-web-list rh-web-list--tight">
          {cell.evidence.map((span) => (
            <li key={span.id} className="rh-web-stack rh-web-stack--tight">
              {span.found && span.route ? (
                <Link to={href(span.route)}>
                  {humaniseResearchTokens(span.title)}{' '}
                  <code className="rh-web-object-id">{span.id}</code>
                </Link>
              ) : (
                <span>
                  <code className="rh-web-object-id">{span.id}</code>
                  <span className="rh-text-secondary">
                    {' '}
                    — this workspace no longer holds it
                  </span>
                </span>
              )}
              {span.measurement && span.measurement !== cell.measurement ? (
                <p>{span.measurement}</p>
              ) : null}
              {span.quote ? <blockquote className="rh-web-quote">{span.quote}</blockquote> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
