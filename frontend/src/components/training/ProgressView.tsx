'use client';

import Link from 'next/link';
import { formatDate } from '@/lib/format';
import { scoreBadge } from '@/lib/intelligence';
import type { SkillRow, TrainingProgress } from '@/lib/types';
import { DataTable, type Column } from '../DataTable';
import { EmptyState } from '../EmptyState';

/** A horizontal bar for a 0-100 value (or a share of `max`). The number is always shown next to it. */
export function Bar({ value, max = 100, label }: { value: number; max?: number; label: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (100 * value) / max)) : 0;
  return (
    <span className="bar" role="img" aria-label={label}>
      <span className="bar-track" aria-hidden="true">
        <span className="bar-fill" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

/** Average score tile: the number when there is one, otherwise a plain "No score yet". */
export function ScoreValue({ score }: { score: number | null }) {
  if (score === null || score === undefined) return <span className="stat-empty">No score yet</span>;
  return (
    <>
      {score}
      <span className="stat-unit"> / 100</span>
    </>
  );
}

function Trend({ trend, sessionHref }: { trend: TrainingProgress['trend']; sessionHref: (id: string) => string }) {
  if (trend.length === 0) return <p className="muted">No scored sessions yet. Scores show up here after a session is evaluated.</p>;
  return (
    <ol className="trend" aria-label="Scores of your latest evaluated sessions, oldest first">
      {trend.map((t) => (
        <li key={t.session_id} className="trend-item">
          <Link href={sessionHref(t.session_id)} className="trend-link" aria-label={`Score ${t.score} out of 100 on ${formatDate(t.date)}. Open the session.`}>
            <span className="trend-value" aria-hidden="true">
              {t.score}
            </span>
            <span className="trend-col" aria-hidden="true">
              <span className="trend-bar" style={{ height: `${Math.max(2, Math.min(100, t.score))}%` }} />
            </span>
            <span className="trend-date small muted" aria-hidden="true">
              {formatDate(t.date)}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

function SkillList({ title, items, empty }: { title: string; items: SkillRow[]; empty: string }) {
  return (
    <section className="panel" aria-label={title}>
      <h3 className="panel-title">{title}</h3>
      {items.length === 0 ? (
        <p className="small muted">{empty}</p>
      ) : (
        <ul className="feedback-list">
          {items.map((s) => (
            <li key={s.key}>
              <strong>{s.name}</strong> · {s.average} / 100 <span className="small muted">from {s.samples} sessions</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function SkillsTable({ skills, caption }: { skills: SkillRow[]; caption: string }) {
  const columns: Column<SkillRow>[] = [
    { key: 'name', header: 'Skill', render: (s) => <span className="cell-strong">{s.name}</span> },
    {
      key: 'avg',
      header: 'Average',
      render: (s) => (
        <span className="bar-row">
          <Bar value={s.average} label={`${s.average} out of 100`} />
          <span>{s.average} / 100</span>
        </span>
      ),
    },
    { key: 'samples', header: 'Scored sessions', align: 'end', render: (s) => s.samples },
  ];
  return <DataTable caption={caption} columns={columns} rows={skills} rowKey={(s) => s.key} empty={<EmptyState title="No skills have been scored yet." />} />;
}

/** One person's training progress: numbers, score trend, skills and recent feedback. */
export function ProgressView({
  progress,
  sessionHref,
  self,
}: {
  progress: TrainingProgress;
  sessionHref: (id: string) => string;
  /** True on the trainee's own page (wording uses "you"). */
  self: boolean;
}) {
  const p = progress;
  return (
    <>
      <dl className="stats">
        <div className="stat">
          <dt>Practice sessions</dt>
          <dd>{p.practice_sessions}</dd>
        </div>
        <div className="stat">
          <dt>Scored sessions</dt>
          <dd>{p.evaluated_sessions}</dd>
        </div>
        <div className="stat">
          <dt>Not scored</dt>
          <dd>{p.not_evaluated_sessions}</dd>
        </div>
        <div className="stat">
          <dt>Average score</dt>
          <dd>
            <ScoreValue score={p.average_score} />
          </dd>
        </div>
        <div className="stat">
          <dt>Practice minutes</dt>
          <dd>{p.practice_minutes}</dd>
        </div>
      </dl>
      <p className="small muted">{p.rules}</p>

      <section className="panel" aria-labelledby="trend-title">
        <h2 id="trend-title" className="panel-title">
          Score trend
        </h2>
        <Trend trend={p.trend} sessionHref={sessionHref} />
      </section>

      <div className="var-grid">
        <SkillList title="Strongest skills" items={p.strongest} empty="Skills show up after at least two scored sessions." />
        <SkillList title="Needs work" items={p.needs_work} empty="Skills show up after at least two scored sessions." />
      </div>

      <section aria-labelledby="skills-title">
        <h2 id="skills-title">All skills</h2>
        <SkillsTable skills={p.skills} caption="Average score per skill" />
      </section>

      <section aria-labelledby="feedback-title">
        <h2 id="feedback-title">Recent feedback</h2>
        {p.recent_feedback.length === 0 ? (
          <EmptyState title="No feedback yet.">
            <p>{self ? 'Feedback shows up after one of your sessions is evaluated.' : 'Feedback shows up after one of their sessions is evaluated.'}</p>
          </EmptyState>
        ) : (
          <ul className="card-list">
            {p.recent_feedback.map((f) => (
              <li key={f.session_id} className="card">
                <div className="card-main">
                  <p className="card-meta">
                    <span className={scoreBadge(f.score)}>{f.score} / 100</span> {formatDate(f.date)}
                  </p>
                  {f.summary && <p className="small">{f.summary}</p>}
                  {f.improvements.length > 0 && (
                    <ul className="feedback-list small">
                      {f.improvements.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <Link href={sessionHref(f.session_id)} className="btn btn-secondary btn-sm">
                  Open session
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
