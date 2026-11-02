import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Right-align numbers, etc. */
  align?: 'start' | 'end';
}

export interface DataTableProps<T> {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Shown instead of the table when there are no rows. */
  empty: ReactNode;
  /** Hide the caption visually (screen readers still read it). */
  hideCaption?: boolean;
}

/** A plain semantic table. On narrow screens each row becomes a stacked card (labels come from data-label). */
export function DataTable<T>({ caption, columns, rows, rowKey, empty, hideCaption = true }: DataTableProps<T>) {
  if (rows.length === 0) return <>{empty}</>;
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className={hideCaption ? 'visually-hidden' : 'table-caption'}>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.align === 'end' ? 'align-end' : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => {
                const content = c.render(row);
                return (
                  <td key={c.key} data-label={c.header} className={c.align === 'end' ? 'align-end' : undefined}>
                    {content === null || content === undefined || content === false ? null : <div className="cell">{content}</div>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
