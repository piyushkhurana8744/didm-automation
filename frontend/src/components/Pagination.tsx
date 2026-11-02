import { Button } from './Button';

/** "Showing 1–25 of 80" with previous/next buttons. Renders nothing when everything fits on one page. */
export function Pagination({
  total,
  limit,
  offset,
  onChange,
  noun = 'items',
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  noun?: string;
}) {
  if (total <= limit && offset === 0) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label={`Pages of ${noun}`}>
      <p className="muted small" aria-live="polite">
        Showing {from}–{to} of {total} {noun}
      </p>
      <div className="row">
        <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
