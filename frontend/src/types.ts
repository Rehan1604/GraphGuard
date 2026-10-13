export type Priority = 'low' | 'medium' | 'high'
export type Status = 'new' | 'in_review' | 'escalated' | 'dismissed'
export type Rule = 'pass_through_chain' | 'cycle' | 'burst' | 'fan'

export interface Transaction {
  id: string
  source_account_id: string
  target_account_id: string
  amount: string // decimal text such as "250.00": never a float
  currency: string
  timestamp: string
  ingested_at: string
}

export interface AlertSummary {
  id: number
  rule: Rule
  risk_score: number
  priority: Priority
  summary: string
  accounts: string[]
  status: Status
  window_start: string
  window_end: string
  evidence_count: number
  created_at: string
  updated_at: string
  ml_score?: number | null // triage estimate that this is a genuine pattern; null = not scored
  ml_verdict?: 'likely_true' | 'likely_benign' | null
}

export interface MlDriver {
  label: string
  value: number
  effect: number // change in the estimate caused by this feature
  direction: 'raises' | 'lowers'
}

export interface ScoreContribution {
  reason: string
  points: number
}

export interface Note {
  id: number
  alert_id: number
  author: string
  body: string
  created_at: string
}

export interface HistoryEvent {
  id: number
  event: string
  from_status: Status | null
  to_status: Status | null
  actor: string
  comment: string | null
  created_at: string
}

export interface AlertDetail extends AlertSummary {
  contributions: ScoreContribution[]
  evidence: Transaction[] // facts from the data
  notes: Note[] // opinions from people
  history: HistoryEvent[]
  allowed_next_statuses: Status[]
  comment_required_for: Status[]
  ml_model?: string | null
  ml_drivers?: MlDriver[]
}

export interface Stats {
  accounts: number
  transactions: number
  alerts_total: number
  alerts_open: number
}

export interface AlertMetrics {
  total: number
  by_status: Record<Status, number>
  by_priority: Record<Priority, number>
  by_rule: Record<Rule, number>
}

export interface GraphNode {
  id: string
  name: string
  account_type: 'individual' | 'business'
  open_alerts: number
}

export interface GraphEdge {
  source: string
  target: string
  transaction_count: number
  total_amount: string
  currency: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  transactions_considered: number
}

export type SimulationStatus = 'stopped' | 'running' | 'paused' | 'error'

export interface SimulationState {
  status: SimulationStatus
  events_emitted: number
  transactions_created: number
  duplicates_ignored: number
  errors: number
  events_per_second: number
  seed: number | null
  duplicate_rate: number
  sim_time: string | null
}

export interface StartOptions {
  events_per_second: number
  seed: number
  duplicate_rate: number
}

export interface DetectionConfig {
  pass_through_ratio: number
  chain_hop_window_minutes: number
  min_chain_hops: number
  max_chain_hops: number
  cycle_window_minutes: number
  min_cycle_length: number
  max_cycle_length: number
  cycle_min_amount_ratio: number
  burst_window_minutes: number
  burst_min_transactions: number
  fan_min_counterparties: number
}

export interface Finding {
  rule: Rule
  accounts: string[]
  transaction_ids: string[]
  risk_score: number
  priority: Priority
  summary: string
}

export interface DetectionResult {
  transactions_analyzed: number
  accounts_in_graph: number
  connected_groups: number
  findings: Finding[]
}

export interface ScanSummary {
  findings: number
  created: number
  updated: number
  unchanged: number
}

// Messages the server pushes over the WebSocket
export type ServerMessage =
  | { type: 'hello'; current_seq: number; replayed: number }
  | { type: 'resync_required'; current_seq: number }
  | { seq: number; type: 'transaction'; data: Transaction }
  | { seq: number; type: 'alert'; data: { action: 'created' | 'updated'; alert: AlertSummary } }
  | { seq: number; type: 'simulation'; data: SimulationState }
  | { seq: number; type: 'reset'; data: Record<string, never> }

// ---- Assistant (Milestone 7)
export interface Fact {
  id: string // F1, F2, ... computed from the stored transactions
  text: string
  kind: 'summary' | 'evidence' | 'score' | 'triage'
}

export interface Passage {
  id: string // K1, K2, ... from the guidance library
  source: string
  title: string
  section: string
  text: string
  score: number
  via: 'similarity' | 'rule_default'
}

export interface AnswerSection {
  heading: string
  items: string[]
}

export interface Explanation {
  mode: 'ai' | 'rule_based'
  label: string
  provider: string | null
  model: string | null
  sections: AnswerSection[]
  citations: string[]
  invalid_citations_removed: string[]
  warnings: string[]
  privacy_note: string | null
}

export interface CaseMatch {
  id: string // C1, C2, ... a past reviewed alert in this workspace
  alert_id: number
  rule: string
  status: string
  summary: string
  comment: string // shown here; never sent to an AI provider
  score: number
}

export interface RetrievalInfo {
  embedder: string
  note: string
  library_passages: number
}

export interface AssistantAnswer {
  alert_id: number
  question: string
  facts: Fact[]
  guidance: Passage[]
  similar_cases?: CaseMatch[]
  retrieval?: RetrievalInfo | null
  explanation: Explanation
  disclaimer: string
}

export interface AssistantStatus {
  ai_configured: boolean
  provider: string
  model: string | null
  problem: string | null
  privacy: string
}
// ---- Evaluation (Milestone 8)
export interface Rate {
  numerator: number
  denominator: number
  value: number | null // null = undefined (nothing out of nothing), which is not the same as 0
}

export interface Confusion {
  true_positive: number
  false_negative: number
  false_positive: number
  true_negative: number
}

export interface DetectorResult {
  name: string
  findings: number
  precision: Rate
  recall: Rate
  recall_lenient: Rate
  f1: number | null
  per_kind_recall: Record<string, Rate>
  confusion: Confusion
  false_positive_findings: number
  false_positives_from_benign_lookalikes: number
  false_positives_from_near_misses: number
  false_positives_mixed_overlap: number
  false_positives_background_only: number
  benign_lookalikes_flagged: Rate
  near_misses_flagged: Rate
  background_only_findings_per_1000_background: number | null
}

export interface DelayStats {
  detected: number
  median_minutes_from_first_transfer: number | null
  max_minutes_from_first_transfer: number | null
  median_minutes_after_last_transfer: number | null
  flagged_before_pattern_finished: Rate
  median_by_kind: Record<string, number>
}

export interface SweepPoint {
  value: number
  findings: number
  precision: number | null
  recall: number | null
  f1: number | null
}

export interface Sweep {
  parameter: string
  description: string
  default: number
  points: SweepPoint[]
}

export interface TriageEvaluation {
  model_version: string
  threshold: number
  result: DetectorResult
  alerts_removed: number
  seed_overlaps_training: boolean
  recorded: Record<string, unknown>
  caveats: string[]
}

export interface EvaluationReport {
  triage?: TriageEvaluation | null
  dataset: {
    name: string
    seed: number
    transactions: number
    background_transactions: number
    episodes_by_role: Record<string, number>
    positives_by_kind: Record<string, number>
  }
  graph: DetectorResult
  baseline: DetectorResult
  delay: DelayStats
  sweeps: Sweep[]
  negative_control: { description: string; recall: Rate }
  timing: { streaming_seconds: number; milliseconds_per_transaction: number }
  caveats: string[]
}