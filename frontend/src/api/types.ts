export interface ApiEnvelope<T> {
  data: T;
  message: string;
  request_id: string | null;
  errors: null | { code: string; details: Record<string, unknown> };
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface BaseEntity {
  id: number;
  created_at?: string;
  updated_at?: string;
}

export interface Demand extends BaseEntity {
  report_id: string;
  customer_id: number | null;
  model_name: string;
  expected_tpm: number;
  expected_rpm: number;
  discount_rate: number;
  expected_start_at: string | null;
  expected_end_at: string | null;
  status: string;
  source_batch_id: number | null;
  source_payload_hash: string | null;
  field_completeness_score: number;
  extra?: Record<string, unknown>;
}

export interface Evaluation extends BaseEntity {
  demand_id: number;
  feasibility_score: number;
  customer_value_score: number;
  expected_revenue: number;
  expected_cost: number;
  expected_margin: number;
  factors_json: Record<string, unknown>;
  recommendation: string;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  decided_reason: string | null;
}

export interface DemandDetail {
  demand: Demand;
  latest_evaluation: Evaluation | null;
  policy?: Policy | null;
}


export interface PolicyRun extends BaseEntity {
  run_no: string;
  triggered_by: string;
  algorithm: string;
  input_hash: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

export interface Policy extends BaseEntity {
  policy_run_id: number;
  policy_no: string;
  algorithm: string;
  summary_json: Record<string, unknown>;
  expected_revenue_gain: number;
  expected_peak_shaving_gain: number;
  expected_off_peak_gain: number;
  constraints_json: Record<string, unknown>;
  status: string;
  accepted_by: string | null;
  accepted_at: string | null;
  cancel_reason: string | null;
  effective_from: string | null;
  effective_to: string | null;
}

export interface PolicyAction extends BaseEntity {
  policy_id: number;
  action_type: string;
  payload_json: Record<string, unknown>;
  expected_gain: number;
}

export interface PolicyDetail {
  policy: Policy;
  actions: PolicyAction[];
}

export interface PolicyReport {
  policy_id: number;
  algorithm: string;
  kpis: Record<string, number>;
  unit_example: Record<string, unknown> | null;
  attributions: Record<string, unknown>[];
  cluster_utilization: Record<string, unknown>[];
  peak_feasibility: Record<string, unknown>;
  model_rebalance: Record<string, unknown> | null;
}

export interface RevenueAttribution extends BaseEntity {

  policy_id: number;
  mechanism: string;
  project_code: string;
  project_name: string | null;
  revenue_delta: number;
  cost_delta: number;
  margin_delta: number;
  allocation_ratio: number;
  computed_at: string;
}

export interface RevenueAnalysisItem {
  policy_id: number;
  policy_no: string;
  algorithm: string;
  policy_status: string;
  expected_revenue_gain: number;
  actual_revenue_gain: number;
  revenue_gap: number;
  achievement_status: 'achieved' | 'not_achieved';
  analysis_reason: string;
  archived: boolean;
  archived_by: string | null;
  archived_at: string | null;
}

export interface RevenueAnalysisOverview {
  total: number;
  achieved: number;
  not_achieved: number;
  achieved_ratio: number;
  not_achieved_ratio: number;
  by_algorithm: Record<string, { achieved: number; not_achieved: number; total: number }>;
}

export interface RevenueAnalysis {
  underperforming: RevenueAnalysisItem[];
  overview: RevenueAnalysisOverview;
  items: RevenueAnalysisItem[];
}

export interface RevenueTimePeriodItem {
  id: number;
  date: string;
  customer_name: string;
  model_name: string;
  sale_discount: number;
  purchase_discount: number;
  self_incremental_revenue: number;
  vendor_cost_reduction: number;
  total_revenue: number;
  price_per_million_tokens: number;
}

export interface RevenuePeakShavingItem {
  id: number;
  date: string;
  customer_name: string;
  model_name: string;
  peak_tpm_before: number;
  peak_watermark: number;
  saved_tpm: number;
  machines_before: number;
  machines_after: number;
  self_cost_reduction: number;
  vendor_cost_increase: number;
  directed_shift_revenue: number;
}

export interface RevenueDashboard {
  generated_at: string;
  idle: RevenueTimePeriodItem[];
  busy: RevenueTimePeriodItem[];
  peak_shaving: RevenuePeakShavingItem[];
}

export interface VendorQuota extends BaseEntity {
  vendor: string;
  model: string;
  quota_tpm: number;
  actual_tpm: number;
  actual_redundant_tpm: number;
  unit_cost: number;
  unit_price: number;
  purchase_discount: number;
  effective_from: string;
  effective_to: string | null;
  status: string;
  contact: string | null;
  notes: string | null;
  raw_json: Record<string, unknown>;
}

export interface AlertItem extends BaseEntity {
  alert_type: string;
  severity: string;
  subject_type: string | null;
  subject_id: string | null;
  message: string;
  payload_json: Record<string, unknown>;
  status: string;
  acked_by: string | null;
  acked_at: string | null;
  closed_at: string | null;
}

export interface SyncBatch extends BaseEntity {
  batch_no: string;
  source: string;
  triggered_by: string;
  started_at: string;
  finished_at: string | null;
  total_pulled: number;
  total_inserted: number;
  total_updated: number;
  total_skipped: number;
  status: string;
  error_message: string | null;
}

export interface RawFiling extends BaseEntity {
  batch_id: number;
  report_id: string;
  payload_json: Record<string, unknown>;
  pulled_at: string;
  hash: string;
}

export interface DashboardOperations {
  pending_demands: number;
  pending_evaluations: number;
  draft_policies: number;
  revenue_last_24h: number;
  open_alerts: number;
}

export interface ResourceNode {
  node_id: string;
  gpu_model: string;
  datacenter: string;
  az: string;
  capacity_tpm: number;
  available_tpm: number;
  utilization: number;
  [key: string]: unknown;
}

export interface ResourceCluster {
  cluster_name: string;
  deployed_model: string;
  primary_customer: string | null;
  provider?: string;
  machine_count: number;
  tpm_per_machine: number;
  tpm_per_machine_w?: number;
  total_capacity_tpm: number;
  total_capacity_w?: number;
  peak_tpm_idle?: number;
  idle_redundant_tpm?: number;
  idle_redundant_machines?: number;
  peak_tpm_busy?: number;
  busy_redundant_tpm?: number;
  busy_redundant_machines?: number;
  current_tpm: number;
  current_tpm_w?: number;
  current_redundant_tpm: number;
  current_redundant_w?: number;
  current_redundant_machines?: number;
  cluster_utilization?: number;
  [key: string]: unknown;
}

export interface ResourceDashboard {
  captured_at: string | null;
  total_capacity_tpm: number;
  total_available_tpm: number;
  avg_utilization: number;
  nodes: ResourceNode[];
  clusters?: ResourceCluster[];
}

export interface ClusterTpmSnapshot extends BaseEntity {
  batch_id: number;
  data_time: string;
  cluster_name: string;
  tpm: number;
  node_count: number;
  node_avg_tpm: number;
}

export interface ConsumerTpmSnapshot extends BaseEntity {
  batch_id: number;
  data_time: string;
  ai_consumer: string;
  customer_code: string | null;
  ai_model: string;
  tpm: number;
  self_ratio: number | null;
  thirdparty_ratio: number | null;
  avg_input_token: number | null;
  avg_output_token: number | null;
  cache_hit_rate: number | null;
}

export interface MonitorSnapshot<T> {
  batch_id: number | null;
  items: T[];
}

export interface FittingAlgorithm extends BaseEntity {
  algo_name: string;
  display_name: string;
  description: string;
  entry_ref: string;
  enabled: boolean;
  default_params: Record<string, unknown>;
}

export interface FittingConfig extends BaseEntity {
  customer_code: string;
  model_name: string;
  period: 'idle' | 'busy';
  algo_name: string;
  params_json: Record<string, unknown>;
  enabled: boolean;
}

export interface FittingResult extends BaseEntity {
  level: 'customer' | 'cluster';
  customer_code: string | null;
  cluster_name: string | null;
  model_name: string;
  period: 'idle' | 'busy';
  algo_name: string;
  generated_at: string;
  series_json: Array<[string, number]>;
  meta_json: Record<string, unknown>;
}

export interface FittingResultsResponse {
  items: FittingResult[];
  total: number;
}

export interface WatchedCluster extends BaseEntity {
  cluster_name: string;
  enabled: boolean;
  sort_order: number;
}

export interface JobSchedule extends BaseEntity {
  job_name: string;

  description: string;
  trigger_type: 'cron' | 'interval' | string;
  cron_expr: string | null;
  interval_seconds: number | null;
  enabled: boolean;
  args_json: Record<string, unknown>;
  last_run_at: string | null;
  next_run_at: string | null;
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;
export type UnknownRecord = Record<string, unknown>;

