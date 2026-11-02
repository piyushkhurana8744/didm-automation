'use client';

import { api, seg } from '@/lib/api';
import { DIFFICULTY_LABELS, orgPath, parseOptionalInt } from '@/lib/agents';
import type { AssignmentSettings, Scenario } from '@/lib/types';
import { useLoad } from '@/lib/useLoad';
import { CheckList } from './CheckList';
import { TextField } from './Field';
import { SkeletonRows } from './Spinner';

export interface SettingsDraft {
  scenarioIds: string[];
  maxSessions: string;
  maxMinutes: string;
}

export function settingsDraftFrom(s: AssignmentSettings | null | undefined): SettingsDraft {
  return {
    scenarioIds: s?.allowed_scenario_ids ?? [],
    maxSessions: s?.max_sessions ? String(s.max_sessions) : '',
    maxMinutes: s?.max_minutes_per_session ? String(s.max_minutes_per_session) : '',
  };
}

/** Checks the limit inputs; returns the settings body or field errors. */
export function settingsFromDraft(
  d: SettingsDraft,
  withScenarios: boolean,
): { settings: AssignmentSettings; errors: Partial<Record<'maxSessions' | 'maxMinutes', string>> } {
  const errors: Partial<Record<'maxSessions' | 'maxMinutes', string>> = {};
  const settings: AssignmentSettings = {};
  const sessions = parseOptionalInt(d.maxSessions);
  if (sessions !== undefined) {
    if (Number.isNaN(sessions) || sessions < 1 || sessions > 10000) errors.maxSessions = 'A whole number from 1 to 10000, or empty for no limit.';
    else settings.max_sessions = sessions;
  }
  const minutes = parseOptionalInt(d.maxMinutes);
  if (minutes !== undefined) {
    if (Number.isNaN(minutes) || minutes < 1 || minutes > 180) errors.maxMinutes = 'A whole number from 1 to 180, or empty for no limit.';
    else settings.max_minutes_per_session = minutes;
  }
  if (withScenarios && d.scenarioIds.length) settings.allowed_scenario_ids = d.scenarioIds;
  return { settings, errors };
}

/** Allowed scenarios (when one agent is chosen) and session limits. */
export function AssignmentSettingsFields({
  orgId,
  agentId,
  value,
  onChange,
  errors,
}: {
  orgId: string;
  /** The single agent being assigned, or null when several (scenarios cannot be limited then). */
  agentId: string | null;
  value: SettingsDraft;
  onChange: (next: SettingsDraft) => void;
  errors: Partial<Record<'maxSessions' | 'maxMinutes', string>>;
}) {
  const scenarios = useLoad(
    agentId ? () => api.get<Scenario[]>(orgPath(orgId, `/agents/${seg(agentId)}/scenarios?status=active`)) : null,
    agentId ? `${orgId}|${agentId}` : null,
  );
  return (
    <>
      {agentId ? (
        scenarios.loading && !scenarios.data ? (
          <SkeletonRows rows={2} label="Loading scenarios" />
        ) : scenarios.error ? (
          <p className="field-error">Scenarios could not be loaded. Access will cover every active scenario.</p>
        ) : (
          <CheckList
            legend="Allowed scenarios"
            hint="Leave all unchecked to allow every active scenario, including ones added later."
            options={[
              ...(scenarios.data ?? []).map((s) => ({ value: s.id, label: s.name, meta: DIFFICULTY_LABELS[s.difficulty] })),
              // Keep previously chosen scenarios that are no longer active visible, so they can be unchecked
              ...value.scenarioIds
                .filter((id) => !(scenarios.data ?? []).some((s) => s.id === id))
                .map((id) => ({ value: id, label: 'Scenario no longer active', meta: id })),
            ]}
            selected={value.scenarioIds}
            onChange={(ids) => onChange({ ...value, scenarioIds: ids })}
            empty="This agent has no active scenarios yet. Access will cover every scenario activated later."
          />
        )
      ) : (
        <p className="field-hint">Allowed scenarios can be chosen when exactly one agent is selected.</p>
      )}
      <div className="form-grid">
        <TextField
          label="Max sessions (optional)"
          type="number"
          inputMode="numeric"
          min={1}
          max={10000}
          step={1}
          value={value.maxSessions}
          error={errors.maxSessions}
          onChange={(e) => onChange({ ...value, maxSessions: e.target.value })}
          hint="Empty means no limit."
        />
        <TextField
          label="Max minutes per session (optional)"
          type="number"
          inputMode="numeric"
          min={1}
          max={180}
          step={1}
          value={value.maxMinutes}
          error={errors.maxMinutes}
          onChange={(e) => onChange({ ...value, maxMinutes: e.target.value })}
          hint="Up to 180. Empty means no limit."
        />
      </div>
    </>
  );
}
