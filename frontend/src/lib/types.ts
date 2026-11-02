export type Role = 'organization_owner' | 'organization_admin' | 'trainer' | 'trainee';

export type Permission =
  | 'org.view'
  | 'members.view'
  | 'members.manage'
  | 'invitations.manage'
  | 'org.update'
  | 'audit.view'
  | 'training.self'
  | 'agents.view'
  | 'agents.manage'
  | 'knowledge.view'
  | 'knowledge.content.view'
  | 'knowledge.manage'
  | 'agents.preview'
  | 'agents.provider_test'
  | 'agents.publish'
  | 'scenarios.manage'
  | 'assignments.manage'
  | 'teams.view'
  | 'teams.manage'
  | 'training.view'
  | 'training.manage'
  | 'rubrics.manage'
  | 'evaluations.manage'
  | 'recordings.view'
  | 'recordings.manage';

export interface User {
  id: string;
  email: string;
  name: string;
  status: string;
  is_platform_admin: boolean;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  status: string;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface Membership {
  membership_id: string;
  organization: Organization;
  role: Role;
  permissions: Permission[];
}

export interface Me {
  user: User;
  memberships: Membership[];
  active_organization_id: string | null;
}

export interface LoginResponse {
  user: User;
  active_organization_id: string | null;
}

export interface OrganizationDetail extends Organization {
  role: Role;
  permissions: Permission[];
  active_members: number;
  pending_invitations: number;
}

export interface DashboardSummary {
  total_trainees: number;
  active_trainees: number;
  active_agents: number;
  assigned_trainees: number;
  training_sessions: number;
  average_score: number | null;
  pending_invitations: number;
  recent_activity: Array<{ id: string; action: string; target_type: string | null; created_at: string }>;
}

export interface Member {
  membership_id: string;
  user: User;
  role: Role;
  status: string;
  joined_at: string;
}

export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  status: InvitationStatus;
  expires_at: string;
  created_at: string;
}

export interface IssuedInvitation extends Invitation {
  accept_url: string;
  emailed: boolean;
}

export interface AuditEvent {
  id: number | string;
  action: string;
  actor_user_id: string | null;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface InvitationLookup {
  organization: { id: string; name: string };
  email: string;
  role: Role;
  has_account: boolean;
  expires_at: string;
}

export interface AcceptResponse {
  ok: boolean;
  organization_id: string;
  role: Role;
  user: User;
}

export interface PlatformOrganization extends Organization {
  active_members: number;
}

export interface PlatformCreateResponse {
  organization: Organization;
  owner_invitation: IssuedInvitation;
}

// ---------- voice agents (phase 2) ----------

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface KnowledgeCapabilities {
  manual: boolean;
  faq: boolean;
  offline_retrieval: boolean;
  file_upload: boolean;
  file_upload_reason: string;
  sarvam_sync: boolean;
  sarvam_sync_reason: string;
}

export interface KnowledgeLibrary {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  library_id: string;
  kind: 'file' | 'faq' | 'manual';
  title: string;
  status: 'active' | 'archived';
  current_revision_id: string | null;
  created_at: string;
  updated_at: string;
  revision: null | {
    id: string;
    revision_no: number;
    processing_state: string;
    malware_state: string;
    source_locale: string | null;
    sha256: string | null;
    created_at: string;
  };
}

export type Channel = 'phone' | 'browser';
export type AgentStatus = 'active' | 'archived';

export interface Agent {
  id: string;
  name: string;
  description: string;
  category: string;
  provider: string;
  provider_app_id: string;
  channels: Channel[];
  status: AgentStatus;
  published_version_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface AgentListItem extends Agent {
  published_internal_version: number | null;
  published_provider_app_version: number | null;
  has_draft: boolean;
}

export type VarType = 'string' | 'number' | 'integer' | 'boolean' | 'enum';

export interface VarDef {
  name: string;
  type: VarType;
  required?: boolean;
  description?: string;
  options?: string[];
  max_length?: number;
  min?: number;
  max?: number;
  default?: string | number | boolean;
}

export type VersionStatus = 'draft' | 'published';

export interface AgentVersion {
  id: string;
  agent_id: string;
  internal_version: number;
  provider_app_version: number | null;
  configuration_snapshot: Record<string, unknown>;
  variable_schema: VarDef[];
  knowledge_base_reference: string;
  rubric_reference: string;
  notes: string;
  behavior_snapshot?: AgentBehavior;
  knowledge_snapshot_id?: string | null;
  provider_sync_id?: string | null;
  validation_report_id?: string | null;
  release_state?: string;
  content_hash?: string | null;
  status: VersionStatus;
  based_on_version_id: string | null;
  created_by: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentBehavior {
  role: 'ai_student_customer' | 'ai_admissions_counsellor';
  persona: string;
  objective: string;
  instructions: string;
  languages: string[];
  default_language: string;
  unknown_answer: string;
  escalation: string;
}

export interface AgentKnowledgeSelection {
  revision_ids: string[];
}

export interface AgentKnowledgeValidation {
  id: string;
  status: 'passed' | 'failed';
  findings: Array<{ code: string; message: string }>;
}

export interface VersionListItem extends AgentVersion {
  is_current: boolean;
}

export interface AgentDetail extends Agent {
  published_version: AgentVersion | null;
  draft_version: AgentVersion | null;
  counts: { scenarios: number; open_assignments: number };
  provider_app_id_locked: boolean;
}

export interface ValidationResult {
  ok: boolean;
  problems: string[];
}

export type Difficulty = 'beginner' | 'intermediate' | 'advanced';
export type ScenarioStatus = 'draft' | 'active' | 'archived';

export interface Scenario {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  difficulty: Difficulty;
  persona: string;
  objective: string;
  opening_context: string;
  expected_behavior: string;
  evaluation_criteria_reference: string;
  agent_variables: Record<string, unknown>;
  validated_version_id: string | null;
  /** The rubric used to score sessions of this scenario; null means the organization default. */
  rubric_id?: string | null;
  status: ScenarioStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Team {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'archived';
  created_at: string;
  archived_at: string | null;
  member_count?: number;
}

export interface TeamMember {
  user_id: string;
  email: string;
  name: string;
  added_at: string;
}

export interface AddTeamMembersResult {
  added: string[];
  already_members: string[];
}

export type AssignmentState = 'active' | 'scheduled' | 'expired' | 'revoked' | 'replaced';

export interface AssignmentSettings {
  allowed_scenario_ids?: string[];
  max_sessions?: number;
  max_minutes_per_session?: number;
}

export interface Assignment {
  id: string;
  agent_id: string;
  agent_name: string | null;
  user_id: string | null;
  user_email: string | null;
  team_id: string | null;
  team_name: string | null;
  assigned_by: string | null;
  starts_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoke_reason: string | null;
  settings: AssignmentSettings;
  state: AssignmentState;
  created_at: string;
}

export interface AssignmentDetail extends Assignment {
  history: Assignment[];
}

export interface AssignResult {
  created: Assignment[];
  skipped: { agent_id: string; user_id?: string; team_id?: string; assignment_id: string }[];
}

export interface MyAgent {
  id: string;
  name: string;
  description: string;
  category: string;
  channels: Channel[];
  version: { id: string; internal_version: number; published_at: string | null; variable_schema?: VarDef[] };
  access: {
    source: 'direct' | 'team';
    expires_at: string | null;
    max_sessions: number | null;
    max_minutes_per_session: number | null;
  };
  training_available: boolean;
  scenario_count: number;
}

export interface MyScenario {
  id: string;
  name: string;
  description: string;
  difficulty: Difficulty;
  objective: string;
}

export interface MyAgentDetail extends MyAgent {
  scenarios: MyScenario[];
}

export interface MyAgentTrainingSource {
  id: string;
  kind: 'text' | 'pdf' | 'transcript';
  title: string;
  text: string;
  created_at: string;
  session_id?: string;
  sha256?: string;
}

export interface MyAgentTrainingProfile {
  instructions: string;
  variable_values: Record<string, unknown>;
  sources: MyAgentTrainingSource[];
  updated_at: string | null;
}

export interface MyAssignment {
  id: string;
  agent_id: string;
  agent_name: string | null;
  team_id: string | null;
  team_name: string | null;
  starts_at: string;
  expires_at: string | null;
  state: AssignmentState;
  settings: AssignmentSettings;
}

// ---------- training sessions (phase 3) ----------

export type SessionStatus = 'requested' | 'preparing' | 'connecting' | 'active' | 'completed' | 'failed' | 'cancelled' | 'timed_out';

export interface TrainingSession {
  id: string;
  user_id: string;
  user_email: string | null;
  agent_id: string;
  agent_name: string | null;
  agent_version_id: string | null;
  provider_app_version: number | null;
  scenario_id: string | null;
  scenario_name: string | null;
  channel: Channel;
  status: SessionStatus;
  terminal: boolean;
  failure_code: string | null;
  failure_reason: string | null;
  /** Masked, like "******1234". */
  phone: string | null;
  max_duration_seconds: number | null;
  started_at: string | null;
  connected_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  billable_seconds: number | null;
  created_at: string;
  updated_at: string;
}

export interface SessionEvent {
  type: string;
  at: string | null;
}

export interface TrainingSessionDetail extends TrainingSession {
  access?: Record<string, unknown>;
  events?: SessionEvent[];
}

export interface StartedSession extends TrainingSessionDetail {
  replayed: boolean;
}

export interface TrainingAvailability {
  enabled: boolean;
  phone: { available: boolean; phone_on_file: string | null; phone_verified: boolean };
  browser: { available: boolean; reason: string | null };
  max_session_minutes: number;
  /** Whether this session may be recorded, and the notice the trainee must accept first. */
  recording?: { available: boolean; consent_version: string | null; consent_text: string; retention_days: number };
  /** The notice the trainee must accept before every practice call, or null when the organization has none. */
  practice_notice?: { version: string; text: string } | null;
}

export interface EffectiveTrainingLimits {
  enabled: boolean;
  phone_enabled: boolean;
  browser_enabled: boolean;
  org_concurrency: number;
  user_concurrency: number;
  sessions_per_day: number;
  session_minutes: number;
  monthly_minutes: number;
  platform_concurrency: number;
}

export interface StoredTrainingLimits {
  enabled?: boolean | null;
  phone_enabled?: boolean | null;
  browser_enabled?: boolean | null;
  max_concurrent_sessions?: number | null;
  max_concurrent_per_user?: number | null;
  max_sessions_per_user_per_day?: number | null;
  max_session_minutes?: number | null;
  monthly_minutes?: number | null;
  evaluation_enabled?: boolean | null;
  recording_allowed?: boolean | null;
  /** Evaluator calls per month; null means the platform default. */
  evaluation_monthly_calls?: number | null;
  /** Evaluator tokens per month; null means the platform default. */
  evaluation_monthly_tokens?: number | null;
}

export interface TrainingLimits {
  organization_id: string;
  stored: StoredTrainingLimits;
  effective: EffectiveTrainingLimits;
  platform: { phone_channel_live: boolean; browser_channel_live: boolean };
}

export interface TrainingUsage {
  month: string;
  limits: EffectiveTrainingLimits;
  billable_minutes: number;
  reserved_minutes: number;
  remaining_minutes: number;
  connected_sessions: number;
  active_sessions: number;
  by_status: Record<string, number>;
  failure_codes: Record<string, number>;
  by_agent: { agent_id: string; agent_name: string | null; sessions: number; billable_minutes: number }[];
}

export interface MemberPhone {
  membership_id: string;
  user_id: string;
  email: string;
  name: string;
  role: Role;
  phone: string | null;
  verified: boolean;
  verified_at: string | null;
  /** How the number was verified: confirmed by an admin, or by a code the person received. */
  verification_method?: 'admin_confirmed' | 'otp' | null;
}

export interface TrainingHealth {
  open_sessions: Record<string, number>;
  platform_capacity: number;
  today: { completed: number; avg_duration_seconds: number; failures: Record<string, number> };
  training_webhooks_today: Record<string, number>;
}

// ---------- training intelligence (phase 4) ----------

export interface JobState {
  /** queued, running, succeeded, skipped or dead. */
  status: string;
  attempts: number;
  error_code: string | null;
}

export type TranscriptStatus = 'complete' | 'partial' | 'missing' | 'failed' | 'not_available' | 'removed';
export type Speaker = 'agent' | 'trainee' | 'unknown';

export interface TranscriptTurn {
  n: number;
  speaker: Speaker;
  text: string;
  start_ms?: number | null;
  end_ms?: number | null;
}

export interface ScorecardTranscript {
  status: TranscriptStatus;
  reason: string | null;
  source?: string | null;
  language?: string | null;
  /** "en_text" means English text from the provider (it may be a translation). */
  text_variant?: string | null;
  turn_count?: number;
  /** When the transcript was removed under the organization's retention policy (status "removed"). */
  purged_at?: string | null;
  job: JobState | null;
  turns: TranscriptTurn[];
}

export interface EvidenceQuote {
  turn: number;
  quote: string;
}

export interface CriterionResult {
  key: string;
  name: string;
  weight: number | null;
  score: number | null;
  insufficient_evidence: boolean;
  unsupported_score_dropped: boolean;
  /** Missing once the transcript is removed under the retention policy. */
  explanation?: string | null;
  improvement: string;
  /** Missing once the transcript is removed under the retention policy. */
  evidence?: EvidenceQuote[] | null;
}

export interface EvaluationFeedback {
  summary?: string | null;
  strengths?: string[];
  improvements?: string[];
  practice_topics?: string[];
}

export type EvaluationStatus = 'completed' | 'insufficient_evidence' | 'failed';

export interface Evaluation {
  id: string;
  status: EvaluationStatus;
  /** 0 to 100, only when status is completed. */
  overall_score: number | null;
  /** 0 to 100. */
  confidence: number | null;
  rubric: { id: string | null; name: string | null; version_id: string | null; version: number | null; scale_max: number | null };
  evaluator: { provider: string | null; model: string | null; version: string | null };
  criteria: CriterionResult[];
  feedback: EvaluationFeedback;
  error_code: string | null;
  evaluated_at: string | null;
}

export type ScorecardEvaluation =
  | (Evaluation & { job: JobState | null })
  | { status: 'not_evaluated'; reason: string; job: JobState | null };

export type RecordingStatus = 'none' | 'pending' | 'stored' | 'unavailable' | 'failed' | 'deleted';

export interface ScorecardRecording {
  status: RecordingStatus;
  reason: string | null;
  can_play: boolean;
  duration_seconds: number | null;
  retention_until: string | null;
}

export interface Scorecard {
  session: {
    id: string;
    user_id: string;
    agent_id: string;
    agent_name: string | null;
    scenario_id: string | null;
    scenario_name: string | null;
    channel: Channel;
    status: SessionStatus;
    failure_code: string | null;
    created_at: string | null;
    connected_at: string | null;
    ended_at: string | null;
    duration_seconds: number | null;
    practised: boolean;
  };
  provider: { status: string | null; duration_seconds: number | null; reconciliation_status: string | null; reconciled_at: string | null };
  usage: {
    reserved_seconds: number | null;
    billed_seconds: number | null;
    adjustment_seconds: number;
    quota_seconds: number;
    provider_reported_seconds: number | null;
    provider_billing: null;
    provider_billing_note: string;
  };
  transcript: ScorecardTranscript;
  evaluation: ScorecardEvaluation;
  other_evaluations: Evaluation[];
  recording: ScorecardRecording;
}

export interface Playback {
  url: string;
  expires_in_seconds: number;
}

export interface SkillRow {
  key: string;
  name: string;
  /** 0 to 100. */
  average: number;
  samples: number;
}

export interface TrainingProgress {
  practice_sessions: number;
  evaluated_sessions: number;
  not_evaluated_sessions: number;
  average_score: number | null;
  practice_minutes: number;
  trend: { session_id: string; date: string | null; score: number }[];
  skills: SkillRow[];
  strongest: SkillRow[];
  needs_work: SkillRow[];
  recent_feedback: { session_id: string; date: string | null; score: number; summary: string | null; improvements: string[] }[];
  rules: string;
}

export interface TraineeProgress extends TrainingProgress {
  user: { id: string; email: string; name: string };
}

export interface AnalyticsTrainee {
  user_id: string;
  email: string | null;
  name: string | null;
  sessions: number;
  practice_sessions: number;
  evaluated: number;
  average_score: number | null;
  practice_minutes: number;
  last_session_at: string | null;
}

export interface AnalyticsTeam {
  team_id: string;
  name: string;
  members: number;
  active_trainees: number;
  practice_sessions: number;
  evaluated: number;
  average_score: number | null;
}

export interface AnalyticsAgent {
  agent_id: string;
  agent_name: string | null;
  sessions: number;
  completed: number;
  failed: number;
  timed_out: number;
  cancelled: number;
  practice_sessions: number;
  evaluated: number;
  average_score: number | null;
  practice_minutes: number;
}

export interface AnalyticsScenario {
  scenario_id: string;
  scenario_name: string | null;
  practice_sessions: number;
  trainees: number;
  average_score: number | null;
}

export interface TrainingAnalytics {
  period_days: number;
  since: string | null;
  totals: {
    sessions: number;
    practice_sessions: number;
    evaluated_sessions: number;
    average_score: number | null;
    practice_minutes: number;
    active_trainees: number;
  };
  participation: { trainees: number; practised: number };
  score_distribution: Record<string, number>;
  by_channel: { channel: Channel; sessions: number; practice_minutes: number }[];
  trainees: AnalyticsTrainee[];
  trainees_page?: { page: number; page_size: number; total: number };
  teams: AnalyticsTeam[];
  agents: AnalyticsAgent[];
  scenarios: AnalyticsScenario[];
  skills: SkillRow[];
  rules: string;
}

export interface RubricCriterion {
  key: string;
  name: string;
  description: string;
  weight: number;
}

export type RubricStatus = 'active' | 'archived';

export interface RubricVersion {
  id: string;
  rubric_id: string;
  version: number;
  status: 'draft' | 'published';
  criteria: RubricCriterion[];
  weights: Record<string, number>;
  scale_max: number;
  scoring_instructions: string;
  min_trainee_turns: number;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Rubric {
  id: string;
  name: string;
  description: string;
  status: RubricStatus;
  created_at: string;
  updated_at: string;
  published_version?: number | null;
  has_draft?: boolean;
}

export interface RubricDetail extends Rubric {
  versions: RubricVersion[];
}

export interface RubricTemplate {
  criteria: RubricCriterion[];
  scale_max: number;
  min_trainee_turns: number;
}

export interface TrainingSettings {
  recording: {
    available: boolean;
    allowed: boolean;
    enabled: boolean;
    consent_version: string | null;
    consent_text: string;
    retention_days: number;
    provider: 's3' | 'cloudinary' | null;
    allowed_providers: Array<'s3' | 'cloudinary'>;
    reason: string | null;
  };
  default_rubric_id: string | null;
  evaluation: {
    allowed: boolean;
    evaluator_configured: boolean;
    active: boolean;
    evaluator: string | null;
    model: string | null;
    evaluator_version: string;
    /** Why sessions are not scored right now, or null when they are. */
    reason?: string | null;
    budget?: EvaluationBudget;
  };
  provider_lookups: boolean;
  phone_otp: boolean;
  practice_notice?: { text: string; version: string | null };
  retention?: RetentionSettings;
}

export interface EvaluationBudget {
  calls: number;
  call_limit: number;
  tokens: number;
  token_limit: number;
  platform_calls_today: number;
  platform_daily_limit: number;
  max_calls_per_session: number;
  month_start: string;
}

export type RetentionCategory = 'transcripts' | 'recordings' | 'webhook_payloads' | 'browser_tokens' | 'phone_challenges';

export interface RetentionCount {
  due: number;
  removed: number;
  failed: number;
}

export interface RetentionSettings {
  /** null means transcripts are kept indefinitely. */
  transcript_retention_days: number | null;
  recording_retention_days: number;
  legal_hold: boolean;
  legal_hold_reason: string | null;
  legal_hold_set_at: string | null;
  /** When false, the daily job only reports; only expired recordings are removed. */
  enforcement_enabled: boolean;
  platform: { webhook_payload_days: number | null; browser_token_days: number | null; phone_challenge_days: number | null };
  last_run: { status: string; enforced: boolean; counts: Partial<Record<RetentionCategory, RetentionCount>>; started_at: string | null } | null;
}

export interface RetentionRun {
  id?: string | number;
  status: string;
  enforced: boolean;
  counts: Partial<Record<RetentionCategory, RetentionCount>>;
  error?: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RetentionReport extends RetentionSettings {
  due_now: Partial<Record<RetentionCategory, RetentionCount>>;
  runs: RetentionRun[];
}
