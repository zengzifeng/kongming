import type {
  AlertItem,
  DashboardOperations,
  Demand,
  DemandDetail,
  Evaluation,
  Paginated,
  Policy,
  PolicyAction,
  PolicyDetail,
  PolicyRun,
  QueryParams,
  RawFiling,
  ResourceDashboard,
  RevenueAnalysis,
  RevenueAttribution,
  SyncBatch,
  UnknownRecord,
  VendorQuota,
} from './types';

const now = '2026-06-28T10:30:00+08:00';

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function matchQuery(value: unknown, queryValue: unknown) {
  return queryValue === undefined || queryValue === null || queryValue === '' || String(value) === String(queryValue);
}

function paginate<T>(items: T[], query: QueryParams = {}): Paginated<T> {
  const page = Number(query.page || 1);
  const pageSize = Number(query.page_size || 10);
  const start = (page - 1) * pageSize;
  return clone({ items: items.slice(start, start + pageSize), page, page_size: pageSize, total: items.length });
}

function findById<T extends { id: number }>(items: T[], id: number, label: string): T {
  const item = items.find((entry) => entry.id === id) || items[0];
  if (!item) throw new Error(`${label} mock data is empty`);
  return item;
}

const demands: Demand[] = [
  {
    id: 101,
    report_id: 'DR-20260628-001',
    customer_id: 88001,
    model_name: 'ERNIE-4.5-Turbo',
    expected_tpm: 420000,
    expected_rpm: 6800,
    discount_rate: 0.88,
    expected_start_at: '2026-06-29T09:00:00+08:00',
    expected_end_at: '2026-07-28T23:59:59+08:00',
    status: 'awaiting_approval',
    source_batch_id: 301,
    source_payload_hash: 'hash-demand-001',
    field_completeness_score: 0.96,
    created_at: '2026-06-27T11:24:00+08:00',
    updated_at: now,
    extra: { industry: '金融', priority: 'P0', scenario: '智能客服高峰扩容' },
  },
  {
    id: 102,
    report_id: 'DR-20260628-002',
    customer_id: 88018,
    model_name: 'ERNIE-Speed-128K',
    expected_tpm: 260000,
    expected_rpm: 3800,
    discount_rate: 0.92,
    expected_start_at: '2026-07-01T00:00:00+08:00',
    expected_end_at: '2026-08-01T00:00:00+08:00',
    status: 'evaluating',
    source_batch_id: 301,
    source_payload_hash: 'hash-demand-002',
    field_completeness_score: 0.89,
    created_at: '2026-06-27T12:42:00+08:00',
    updated_at: now,
    extra: { industry: '教育', priority: 'P1', scenario: '批改与内容生成' },
  },
  {
    id: 103,
    report_id: 'DR-20260627-009',
    customer_id: 88032,
    model_name: 'Embedding-V2',
    expected_tpm: 180000,
    expected_rpm: 2600,
    discount_rate: 0.8,
    expected_start_at: '2026-06-30T08:00:00+08:00',
    expected_end_at: null,
    status: 'approved',
    source_batch_id: 300,
    source_payload_hash: 'hash-demand-003',
    field_completeness_score: 0.93,
    created_at: '2026-06-26T18:10:00+08:00',
    updated_at: now,
    extra: { industry: '电商', priority: 'P1', scenario: '搜索召回' },
  },
  {
    id: 104,
    report_id: 'DR-20260626-004',
    customer_id: 88045,
    model_name: 'ERNIE-Lite',
    expected_tpm: 90000,
    expected_rpm: 1200,
    discount_rate: 0.95,
    expected_start_at: '2026-07-03T10:00:00+08:00',
    expected_end_at: '2026-07-18T10:00:00+08:00',
    status: 'pending',
    source_batch_id: 299,
    source_payload_hash: 'hash-demand-004',
    field_completeness_score: 0.76,
    created_at: '2026-06-26T10:05:00+08:00',
    updated_at: now,
    extra: { industry: '政企', priority: 'P2', scenario: '知识库问答试点' },
  },
  {
    id: 105,
    report_id: 'DR-20260625-012',
    customer_id: 88001,
    model_name: 'ERNIE-4.5-Turbo',
    expected_tpm: 520000,
    expected_rpm: 7200,
    discount_rate: 0.86,
    expected_start_at: '2026-06-28T14:00:00+08:00',
    expected_end_at: '2026-07-08T14:00:00+08:00',
    status: 'live',
    source_batch_id: 298,
    source_payload_hash: 'hash-demand-005',
    field_completeness_score: 0.98,
    created_at: '2026-06-25T09:20:00+08:00',
    updated_at: now,
    extra: { industry: '金融', priority: 'P0', scenario: '营销活动实时问答' },
  },
];

const evaluations: Evaluation[] = [
  {
    id: 201,
    demand_id: 101,
    feasibility_score: 0.91,
    customer_value_score: 0.94,
    expected_revenue: 1286000,
    expected_cost: 786000,
    expected_margin: 500000,
    factors_json: { capacity_match: 'high', contract_health: 'stable', risk: ['peak overlap 14:00-16:00'] },
    recommendation: 'manual_review',
    status: 'pending',
    decided_by: null,
    decided_at: null,
    decided_reason: null,
    created_at: '2026-06-27T15:30:00+08:00',
    updated_at: now,
  },
  {
    id: 202,
    demand_id: 102,
    feasibility_score: 0.83,
    customer_value_score: 0.86,
    expected_revenue: 642000,
    expected_cost: 418000,
    expected_margin: 224000,
    factors_json: { capacity_match: 'medium', missing_fields: ['目标峰值时段'], suggested_action: '补充业务峰值' },
    recommendation: 'manual_review',
    status: 'draft',
    decided_by: null,
    decided_at: null,
    decided_reason: null,
    created_at: '2026-06-27T16:12:00+08:00',
    updated_at: now,
  },
  {
    id: 203,
    demand_id: 103,
    feasibility_score: 0.95,
    customer_value_score: 0.78,
    expected_revenue: 386000,
    expected_cost: 182000,
    expected_margin: 204000,
    factors_json: { capacity_match: 'high', quota_source: 'self_cluster', margin_level: 'healthy' },
    recommendation: 'auto_approve',
    status: 'approved',
    decided_by: 'ops_lead',
    decided_at: '2026-06-27T18:00:00+08:00',
    decided_reason: '容量与毛利均满足自动通过条件',
    created_at: '2026-06-27T17:21:00+08:00',
    updated_at: now,
  },
  {
    id: 204,
    demand_id: 104,
    feasibility_score: 0.52,
    customer_value_score: 0.61,
    expected_revenue: 96000,
    expected_cost: 112000,
    expected_margin: -16000,
    factors_json: { capacity_match: 'low', blocker: '折扣后毛利为负', suggested_action: '调整折扣或改用闲时资源' },
    recommendation: 'reject',
    status: 'rejected',
    decided_by: 'capacity_admin',
    decided_at: '2026-06-26T16:40:00+08:00',
    decided_reason: '当前折扣与资源成本不匹配',
    created_at: '2026-06-26T15:10:00+08:00',
    updated_at: now,
  },
];

const policyRuns: PolicyRun[] = [
  { id: 401, run_no: 'RUN-20260628-001', triggered_by: 'system', algorithm: 'realtime', input_hash: 'run-input-001', status: 'success', started_at: '2026-06-28T08:00:00+08:00', finished_at: '2026-06-28T08:00:12+08:00', duration_ms: 12430, error_message: null, created_at: '2026-06-28T08:00:00+08:00', updated_at: now },
  { id: 402, run_no: 'RUN-20260628-002', triggered_by: 'frontend', algorithm: 'off_peak', input_hash: 'run-input-002', status: 'running', started_at: '2026-06-28T10:20:00+08:00', finished_at: null, duration_ms: null, error_message: null, created_at: '2026-06-28T10:20:00+08:00', updated_at: now },
  { id: 403, run_no: 'RUN-20260627-006', triggered_by: 'system', algorithm: 'peak_shaving', input_hash: 'run-input-003', status: 'success', started_at: '2026-06-27T23:00:00+08:00', finished_at: '2026-06-27T23:00:19+08:00', duration_ms: 19120, error_message: null, created_at: '2026-06-27T23:00:00+08:00', updated_at: now },
];

const policies: Policy[] = [
  {
    id: 501,
    policy_run_id: 401,
    policy_no: 'POL-REALTIME-0628A',
    algorithm: 'realtime',
    summary_json: { template: '实时策略', target: '金融客户峰值保障', allocation: 'increase priority to cluster-a' },
    expected_revenue_gain: 186000,
    expected_peak_shaving_gain: 42000,
    expected_off_peak_gain: 18000,
    constraints_json: { max_discount: 0.88, protected_customers: [88001], latency_p95_ms: 1800 },
    status: 'draft',
    accepted_by: null,
    accepted_at: null,
    cancel_reason: null,
    effective_from: '2026-06-28T14:00:00+08:00',
    effective_to: '2026-06-29T14:00:00+08:00',
    created_at: '2026-06-28T08:01:00+08:00',
    updated_at: now,
  },
  {
    id: 502,
    policy_run_id: 403,
    policy_no: 'POL-OFFPEAK-0627B',
    algorithm: 'off_peak',
    summary_json: { template: '闲忙时策略', target: '教育批处理任务迁移', window: '00:00-07:00' },
    expected_revenue_gain: 132000,
    expected_peak_shaving_gain: 22000,
    expected_off_peak_gain: 76000,
    constraints_json: { off_peak_window: ['00:00', '07:00'], minimum_margin: 0.28 },
    status: 'accepted',
    accepted_by: 'ops_lead',
    accepted_at: '2026-06-28T09:10:00+08:00',
    cancel_reason: null,
    effective_from: '2026-06-28T23:00:00+08:00',
    effective_to: '2026-07-05T23:00:00+08:00',
    created_at: '2026-06-27T23:01:00+08:00',
    updated_at: now,
  },
  {
    id: 503,
    policy_run_id: 403,
    policy_no: 'POL-PEAK-0627C',
    algorithm: 'peak_shaving',
    summary_json: { template: '削峰策略', target: '14点峰值削减', throttle: 'soft-limit low margin traffic' },
    expected_revenue_gain: 98000,
    expected_peak_shaving_gain: 88000,
    expected_off_peak_gain: 12000,
    constraints_json: { max_throttle_ratio: 0.12, protected_tiers: ['P0', 'P1'] },
    status: 'accepted',
    accepted_by: 'capacity_admin',
    accepted_at: '2026-06-28T07:45:00+08:00',
    cancel_reason: null,
    effective_from: '2026-06-28T12:00:00+08:00',
    effective_to: '2026-06-28T20:00:00+08:00',
    created_at: '2026-06-27T23:02:00+08:00',
    updated_at: now,
  },
  {
    id: 504,
    policy_run_id: 402,
    policy_no: 'POL-REALTIME-0628D',
    algorithm: 'realtime',
    summary_json: { template: '实时策略', target: 'Embedding 召回专线', allocation: 'reserve 12%' },
    expected_revenue_gain: 64000,
    expected_peak_shaving_gain: 8000,
    expected_off_peak_gain: 6000,
    constraints_json: { reserve_capacity_tpm: 120000, datacenter: 'bj-a' },
    status: 'recalculating',
    accepted_by: null,
    accepted_at: null,
    cancel_reason: null,
    effective_from: '2026-06-29T08:00:00+08:00',
    effective_to: null,
    created_at: '2026-06-28T10:21:00+08:00',
    updated_at: now,
  },
  {
    id: 505,
    policy_run_id: 403,
    policy_no: 'POL-BUSY-0712A',
    algorithm: 'time_period',
    summary_json: { template: '忙时策略', module: 'busy', target: '跨模型机器腾挪与切量水位线再平衡', window: '09:00-21:00' },
    expected_revenue_gain: 34902,
    expected_peak_shaving_gain: 34902,
    expected_off_peak_gain: 0,
    constraints_json: { protect_peak_hours: ['09:00-12:00', '18:00-21:00'], keep_peak_feasible: true, rebalance_mode: 'target-rate' },
    status: 'draft',
    accepted_by: null,
    accepted_at: null,
    cancel_reason: null,
    effective_from: '2026-07-12T09:00:00+08:00',
    effective_to: '2026-07-12T21:00:00+08:00',
    created_at: '2026-07-12T01:20:00+08:00',
    updated_at: now,
  },
];

const policyActions: PolicyAction[] = [
  { id: 601, policy_id: 501, action_type: 'reserve_capacity', payload_json: { node_group: 'cluster-a', tpm: 180000, customer_id: 88001 }, expected_gain: 96000, created_at: now, updated_at: now },
  { id: 602, policy_id: 501, action_type: 'adjust_price_guard', payload_json: { minimum_margin: 0.32, discount_floor: 0.86 }, expected_gain: 90000, created_at: now, updated_at: now },
  { id: 603, policy_id: 502, action_type: 'shift_to_off_peak', payload_json: { from: '14:00-18:00', to: '00:00-07:00', demand_ids: [102] }, expected_gain: 76000, created_at: now, updated_at: now },
  { id: 604, policy_id: 503, action_type: 'soft_throttle', payload_json: { model: 'ERNIE-Lite', ratio: 0.08 }, expected_gain: 88000, created_at: now, updated_at: now },
  { id: 605, policy_id: 504, action_type: 'reserve_capacity', payload_json: { node_group: 'embedding-pool', tpm: 120000 }, expected_gain: 64000, created_at: now, updated_at: now },
  { id: 606, policy_id: 505, action_type: 'rebalance_machine_flow', payload_json: { from: 'GLM-5.2', to: 'kimi-k2.5-nvfp4-mihayou', machines: 10, gain_yuan_day: 17576 }, expected_gain: 17576, created_at: now, updated_at: now },
  { id: 607, policy_id: 505, action_type: 'rebalance_machine_flow', payload_json: { from: 'GLM-5.2', to: 'GLM-5.1-FP8', machines: 12, gain_yuan_day: 16643 }, expected_gain: 16643, created_at: now, updated_at: now },
  { id: 608, policy_id: 505, action_type: 'rebalance_machine_flow', payload_json: { from: 'GLM-5.1-KSCC', to: 'kimi-k2.6-mihayou', machines: 1, gain_yuan_day: 683 }, expected_gain: 683, created_at: now, updated_at: now },
];

const vendorQuotas: VendorQuota[] = [
  { id: 701, vendor: '百度', model: 'glm-5.2', quota_tpm: 12000000, actual_tpm: 0, actual_redundant_tpm: 12000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.75, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 1200 万 TPM', raw_json: { source: 'manual-image', quota_w: 1200 }, created_at: now, updated_at: now },
  { id: 702, vendor: '鼎鼎方游（腾讯渠道）', model: 'glm-5.2', quota_tpm: 50000000, actual_tpm: 0, actual_redundant_tpm: 50000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.73, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 5000 万 TPM', raw_json: { source: 'manual-image', quota_w: 5000 }, created_at: now, updated_at: now },
  { id: 703, vendor: '香港锦望', model: 'glm-5.2', quota_tpm: 10000000, actual_tpm: 0, actual_redundant_tpm: 10000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.55, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 1000 万 TPM', raw_json: { source: 'manual-image', quota_w: 1000 }, created_at: now, updated_at: now },
  { id: 704, vendor: '月暗原厂', model: 'kimi-k2.5', quota_tpm: 60000000, actual_tpm: 0, actual_redundant_tpm: 60000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.8, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 6000 万 TPM', raw_json: { source: 'manual-image', quota_w: 6000 }, created_at: now, updated_at: now },
  { id: 705, vendor: '月暗原厂', model: 'kimi-k2.6', quota_tpm: 100000000, actual_tpm: 0, actual_redundant_tpm: 100000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.8, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 10000 万 TPM', raw_json: { source: 'manual-image', quota_w: 10000 }, created_at: now, updated_at: now },
  { id: 706, vendor: '百度', model: 'deepseek-v32', quota_tpm: 12000000, actual_tpm: 0, actual_redundant_tpm: 12000000, unit_cost: 0, unit_price: 0, purchase_discount: 0.4, effective_from: '2026-07-12T00:00:00+08:00', effective_to: null, status: 'active', contact: null, notes: '供应量级 1200 万 TPM', raw_json: { source: 'manual-image', quota_w: 1200 }, created_at: now, updated_at: now },
];

const resourceDashboard: ResourceDashboard = {
  captured_at: now,
  total_capacity_tpm: 1880000,
  total_available_tpm: 632000,
  avg_utilization: 0.664,
  nodes: [
    { node_id: 'km-bj-a-001', gpu_model: 'A800', datacenter: '北京亦庄', az: 'bj-a', capacity_tpm: 520000, available_tpm: 164000, utilization: 0.685, running_models: ['ERNIE-4.5-Turbo', 'ERNIE-Lite'] },
    { node_id: 'km-bj-b-002', gpu_model: 'H800', datacenter: '北京亦庄', az: 'bj-b', capacity_tpm: 680000, available_tpm: 198000, utilization: 0.709, running_models: ['ERNIE-Speed-128K'] },
    { node_id: 'km-gz-a-003', gpu_model: 'A800', datacenter: '广州南沙', az: 'gz-a', capacity_tpm: 420000, available_tpm: 166000, utilization: 0.605, running_models: ['Embedding-V2'] },
    { node_id: 'km-su-a-004', gpu_model: 'L40S', datacenter: '苏州昆山', az: 'su-a', capacity_tpm: 260000, available_tpm: 104000, utilization: 0.6, running_models: ['ERNIE-Lite'] },
  ],
};

const alerts: AlertItem[] = [
  { id: 801, alert_type: 'capacity_pressure', severity: 'critical', subject_type: 'resource_node', subject_id: 'km-bj-b-002', message: '北京 bj-b H800 集群 14:00 峰值预计超过 82%', payload_json: { projected_utilization: 0.82, window: '14:00-16:00' }, status: 'open', acked_by: null, acked_at: null, closed_at: null, created_at: '2026-06-28T09:30:00+08:00', updated_at: now },
  { id: 802, alert_type: 'margin_drop', severity: 'warn', subject_type: 'demand', subject_id: '104', message: 'DR-20260626-004 折扣后毛利为负', payload_json: { margin: -16000, discount_rate: 0.95 }, status: 'ack', acked_by: 'frontend', acked_at: '2026-06-28T10:01:00+08:00', closed_at: null, created_at: '2026-06-28T08:45:00+08:00', updated_at: now },
  { id: 803, alert_type: 'sync_delay', severity: 'info', subject_type: 'sync_batch', subject_id: '301', message: '最新报备同步存在 3 条字段缺失记录', payload_json: { missing_fields: ['expected_end_at', 'customer_id'], count: 3 }, status: 'open', acked_by: null, acked_at: null, closed_at: null, created_at: '2026-06-28T09:05:00+08:00', updated_at: now },
];

const syncBatches: SyncBatch[] = [
  { id: 301, batch_no: 'SYNC-20260628-001', source: 'filing_system', triggered_by: 'system', started_at: '2026-06-28T08:30:00+08:00', finished_at: '2026-06-28T08:30:42+08:00', total_pulled: 56, total_inserted: 9, total_updated: 18, total_skipped: 29, status: 'success', error_message: null, created_at: '2026-06-28T08:30:00+08:00', updated_at: now },
  { id: 300, batch_no: 'SYNC-20260627-003', source: 'filing_system', triggered_by: 'manual', started_at: '2026-06-27T18:00:00+08:00', finished_at: '2026-06-27T18:00:51+08:00', total_pulled: 43, total_inserted: 7, total_updated: 11, total_skipped: 25, status: 'success', error_message: null, created_at: '2026-06-27T18:00:00+08:00', updated_at: now },
];

const rawFilings: RawFiling[] = demands.map((demand, index) => ({
  id: 901 + index,
  batch_id: demand.source_batch_id || 301,
  report_id: demand.report_id,
  payload_json: { customer_id: demand.customer_id, model_name: demand.model_name, expected_tpm: demand.expected_tpm, expected_rpm: demand.expected_rpm, discount_rate: demand.discount_rate, extra: demand.extra },
  pulled_at: demand.created_at || now,
  hash: demand.source_payload_hash || `hash-demand-${index}`,
  created_at: demand.created_at,
  updated_at: now,
}));

const revenueAttributions: RevenueAttribution[] = [
  { id: 1001, policy_id: 501, mechanism: 'capacity_reserve', project_code: 'FIN-P0', project_name: '金融客服峰值保障', revenue_delta: 102000, cost_delta: 46000, margin_delta: 56000, allocation_ratio: 0.55, computed_at: now, created_at: now, updated_at: now },
  { id: 1002, policy_id: 502, mechanism: 'off_peak_shift', project_code: 'EDU-BATCH', project_name: '教育批处理迁移', revenue_delta: 84000, cost_delta: 32000, margin_delta: 52000, allocation_ratio: 0.64, computed_at: now, created_at: now, updated_at: now },
  { id: 1003, policy_id: 503, mechanism: 'peak_shaving', project_code: 'COMMON-PEAK', project_name: '公共峰值削减', revenue_delta: 70000, cost_delta: 21000, margin_delta: 49000, allocation_ratio: 0.71, computed_at: now, created_at: now, updated_at: now },
];

function getRevenueAnalysis(): RevenueAnalysis {
  const items = policies.map((policy, index) => {
    const ratios = [0.91, 1.08, 1.16, 0.72];
    const actual = Math.round(policy.expected_revenue_gain * ratios[index % ratios.length]);
    const gap = actual - policy.expected_revenue_gain;
    return {
      policy_id: policy.id,
      policy_no: policy.policy_no,
      algorithm: policy.algorithm,
      policy_status: policy.status,
      expected_revenue_gain: policy.expected_revenue_gain,
      actual_revenue_gain: actual,
      revenue_gap: gap,
      achievement_status: actual >= policy.expected_revenue_gain ? 'achieved' as const : 'not_achieved' as const,
      analysis_reason: gap >= 0 ? '策略命中高价值时段，实际收益超过预期' : '峰值窗口偏移导致收益释放不足',
      archived: policy.id === 501,
      archived_by: policy.id === 501 ? 'ops_lead' : null,
      archived_at: policy.id === 501 ? '2026-06-28T10:00:00+08:00' : null,
    };
  });
  const achieved = items.filter((item) => item.achievement_status === 'achieved').length;
  const notAchieved = items.length - achieved;
  return clone({
    items,
    underperforming: items.filter((item) => item.achievement_status === 'not_achieved' && !item.archived),
    overview: {
      total: items.length,
      achieved,
      not_achieved: notAchieved,
      achieved_ratio: items.length ? achieved / items.length : 0,
      not_achieved_ratio: items.length ? notAchieved / items.length : 0,
      by_algorithm: items.reduce<Record<string, { achieved: number; not_achieved: number; total: number }>>((acc, item) => {
        const bucket = acc[item.algorithm] || { achieved: 0, not_achieved: 0, total: 0 };
        bucket.total += 1;
        if (item.achievement_status === 'achieved') bucket.achieved += 1;
        else bucket.not_achieved += 1;
        acc[item.algorithm] = bucket;
        return acc;
      }, {}),
    },
  });
}

function filterDemands(query: QueryParams) {
  return demands.filter((item) =>
    matchQuery(item.status, query.status) &&
    matchQuery(item.customer_id, query.customer_id) &&
    (query.model ? item.model_name.toLowerCase().includes(String(query.model).toLowerCase()) : true)
  );
}

function filterEvaluations(query: QueryParams) {
  return evaluations.filter((item) => matchQuery(item.status, query.status) && matchQuery(item.recommendation, query.recommendation));
}

function filterPolicies(query: QueryParams) {
  return policies.filter((item) =>
    matchQuery(item.status, query.status) &&
    matchQuery(item.algorithm, query.algorithm) &&
    matchQuery(item.policy_run_id, query.policy_run_id) &&
    (query.exclude_status ? item.status !== query.exclude_status : true)
  );
}

function filterResources(query: { gpu_model?: string; datacenter?: string }) {
  const nodes = resourceDashboard.nodes.filter((node) =>
    (query.gpu_model ? node.gpu_model.toLowerCase().includes(query.gpu_model.toLowerCase()) : true) &&
    (query.datacenter ? node.datacenter.includes(query.datacenter) : true)
  );
  const totalCapacity = nodes.reduce((sum, node) => sum + node.capacity_tpm, 0);
  const totalAvailable = nodes.reduce((sum, node) => sum + node.available_tpm, 0);
  return clone({
    ...resourceDashboard,
    nodes,
    total_capacity_tpm: totalCapacity,
    total_available_tpm: totalAvailable,
    avg_utilization: totalCapacity ? (totalCapacity - totalAvailable) / totalCapacity : 0,
  });
}

function getPolicyDetail(id: number): PolicyDetail {
  const policy = findById(policies, id, 'Policy');
  return clone({ policy, actions: policyActions.filter((action) => action.policy_id === policy.id) });
}

function getReport(type: 'weekly' | 'monthly', period?: string) {
  const totalRevenue = policies.reduce((sum, item) => sum + item.expected_revenue_gain, 0);
  return clone({
    period: period || (type === 'weekly' ? '2026-W26' : '2026-06'),
    generated_at: now,
    summary: {
      new_demands: demands.length,
      pending_demands: demands.filter((item) => ['pending', 'evaluating', 'awaiting_approval'].includes(item.status)).length,
      accepted_policies: policies.filter((item) => item.status === 'accepted').length,
      expected_revenue_gain: totalRevenue,
      open_alerts: alerts.filter((item) => item.status === 'open').length,
    },
    highlights: [
      'P0 金融客户峰值保障进入待审批',
      '闲忙时策略预计释放 7.6 万低峰收益',
      '北京 bj-b 集群下午峰值需关注容量压力',
    ],
    charts: {
      demand_status: demands.reduce<Record<string, number>>((acc, demand) => ({ ...acc, [demand.status]: (acc[demand.status] || 0) + 1 }), {}),
      policy_gain_by_algorithm: policies.reduce<Record<string, number>>((acc, policy) => ({ ...acc, [policy.algorithm]: (acc[policy.algorithm] || 0) + policy.expected_revenue_gain }), {}),
    },
  });
}

export const mockApi = {
  dashboards: {
    operations: async (): Promise<DashboardOperations> => clone({
      pending_demands: demands.filter((item) => item.status === 'pending' || item.status === 'evaluating').length,
      pending_evaluations: evaluations.filter((item) => item.status === 'pending').length,
      draft_policies: policies.filter((item) => item.status === 'draft').length,
      revenue_last_24h: 428000,
      open_alerts: alerts.filter((item) => item.status === 'open').length,
    }),
    customers: async (customerId?: number): Promise<UnknownRecord> => {
      const scoped = customerId ? demands.filter((item) => item.customer_id === customerId) : demands;
      return clone({
        customer_id: customerId || 'all',
        demand_count: scoped.length,
        active_models: Array.from(new Set(scoped.map((item) => item.model_name))),
        expected_tpm: scoped.reduce((sum, item) => sum + item.expected_tpm, 0),
        expected_revenue: evaluations.filter((item) => scoped.some((demand) => demand.id === item.demand_id)).reduce((sum, item) => sum + item.expected_revenue, 0),
        fulfillment: { live: scoped.filter((item) => item.status === 'live').length, approved: scoped.filter((item) => item.status === 'approved').length, pending: scoped.filter((item) => item.status === 'pending').length },
        recent_demands: scoped.slice(0, 5),
      });
    },
    management: async (range = '7d'): Promise<UnknownRecord> => clone({
      range,
      generated_at: now,
      revenue: { current: 4860000, previous: 4210000, growth: 0.154 },
      cost: { current: 2960000, previous: 2780000, growth: 0.064 },
      margin: { current: 1900000, rate: 0.391 },
      strategy_contribution: policies.map((policy) => ({ policy_no: policy.policy_no, algorithm: policy.algorithm, gain: policy.expected_revenue_gain })),
      trend: [
        { date: '06-22', revenue: 620000, cost: 386000 },
        { date: '06-23', revenue: 690000, cost: 411000 },
        { date: '06-24', revenue: 710000, cost: 430000 },
        { date: '06-25', revenue: 735000, cost: 438000 },
        { date: '06-26', revenue: 760000, cost: 452000 },
        { date: '06-27', revenue: 805000, cost: 486000 },
        { date: '06-28', revenue: 540000, cost: 357000 },
      ],
    }),
    resources: async (query: { gpu_model?: string; datacenter?: string }): Promise<ResourceDashboard> => filterResources(query),
  },
  demands: {
    list: async (query: QueryParams): Promise<Paginated<Demand>> => paginate(filterDemands(query), query),
    detail: async (id: number): Promise<DemandDetail> => clone({ demand: findById(demands, id, 'Demand'), latest_evaluation: evaluations.find((item) => item.demand_id === id) || null }),
    patch: async (id: number, body: UnknownRecord): Promise<Demand> => {
      const demand = findById(demands, id, 'Demand');
      Object.assign(demand, body, { updated_at: now });
      return clone(demand);
    },
    evaluate: async (id: number, force = false): Promise<Evaluation> => {
      const existing = evaluations.find((item) => item.demand_id === id);
      if (existing) return clone(existing);
      const evaluation: Evaluation = { id: Math.max(...evaluations.map((item) => item.id)) + 1, demand_id: id, feasibility_score: 0.82, customer_value_score: 0.8, expected_revenue: 300000, expected_cost: 190000, expected_margin: 110000, factors_json: { generated_by: 'mock', force }, recommendation: 'manual_review', status: 'pending', decided_by: null, decided_at: null, decided_reason: null, created_at: now, updated_at: now };
      evaluations.unshift(evaluation);
      return clone(evaluation);
    },
  },
  evaluations: {
    list: async (query: QueryParams): Promise<Paginated<Evaluation>> => paginate(filterEvaluations(query), query),
    detail: async (id: number): Promise<Evaluation> => clone(findById(evaluations, id, 'Evaluation')),
    approve: async (id: number, body: { operator: string; comment?: string }): Promise<Evaluation> => {
      const evaluation = findById(evaluations, id, 'Evaluation');
      Object.assign(evaluation, { status: 'approved', decided_by: body.operator, decided_at: now, decided_reason: body.comment || '同意评估结论', updated_at: now });
      return clone(evaluation);
    },
    reject: async (id: number, body: { operator: string; reason: string }): Promise<Evaluation> => {
      const evaluation = findById(evaluations, id, 'Evaluation');
      Object.assign(evaluation, { status: 'rejected', decided_by: body.operator, decided_at: now, decided_reason: body.reason, updated_at: now });
      return clone(evaluation);
    },
  },
  policies: {
    createRun: async (body: { algorithm: string; demand_ids?: number[]; params?: UnknownRecord | null }): Promise<PolicyRun> => {
      const run: PolicyRun = { id: Math.max(...policyRuns.map((item) => item.id)) + 1, run_no: `RUN-20260628-${String(policyRuns.length + 1).padStart(3, '0')}`, triggered_by: 'frontend', algorithm: body.algorithm, input_hash: `run-input-${policyRuns.length + 1}`, status: 'running', started_at: now, finished_at: null, duration_ms: null, error_message: null, created_at: now, updated_at: now };
      policyRuns.unshift(run);
      return clone(run);
    },
    runs: async (query: QueryParams): Promise<Paginated<PolicyRun>> => paginate(policyRuns, query),
    run: async (id: number): Promise<PolicyRun> => clone(findById(policyRuns, id, 'Policy run')),
    snapshot: async (id: number): Promise<UnknownRecord> => clone({ run: findById(policyRuns, id, 'Policy run'), demands: demands.slice(0, 3), resources: resourceDashboard.nodes.slice(0, 2), constraints: { min_margin: 0.25, protect_p0: true } }),
    list: async (query: QueryParams): Promise<Paginated<Policy>> => paginate(filterPolicies(query), query),
    detail: async (id: number): Promise<PolicyDetail> => getPolicyDetail(id),
    patch: async (id: number, body: UnknownRecord): Promise<Policy> => {
      const policy = findById(policies, id, 'Policy');
      Object.assign(policy, Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined)), { updated_at: now });
      return clone(policy);
    },
    accept: async (id: number, body: { operator: string; effective_from?: string; comment?: string }): Promise<Policy> => {
      const policy = findById(policies, id, 'Policy');
      Object.assign(policy, { status: 'accepted', accepted_by: body.operator, accepted_at: now, effective_from: body.effective_from || policy.effective_from, updated_at: now });
      return clone(policy);
    },
    recalculate: async (_id?: number, _params?: UnknownRecord | null): Promise<PolicyRun> => mockApi.policies.createRun({ algorithm: 'realtime', params: _params }),
    cancel: async (id: number, body: { operator: string; reason: string }): Promise<Policy> => {
      const policy = findById(policies, id, 'Policy');
      Object.assign(policy, { status: 'cancelled', cancel_reason: body.reason || `cancelled by ${body.operator}`, updated_at: now });
      return clone(policy);
    },
  },
  revenue: {
    attributions: async (query: QueryParams): Promise<Paginated<RevenueAttribution>> => paginate(revenueAttributions, query),
    policyRevenue: async (policyId: number): Promise<UnknownRecord> => clone({ policy_id: policyId, attributions: revenueAttributions.filter((item) => item.policy_id === policyId), analysis: getRevenueAnalysis().items.find((item) => item.policy_id === policyId) }),
    analysis: async (): Promise<RevenueAnalysis> => getRevenueAnalysis(),
    archiveAnalysis: async (_policyId?: number, _body?: { operator: string; reason: string }): Promise<RevenueAnalysis> => getRevenueAnalysis(),
  },
  vendors: {
    quotas: async (query: QueryParams): Promise<Paginated<VendorQuota>> => paginate(vendorQuotas.filter((item) => matchQuery(item.status, query.status)), query),
  },
  alerts: {
    list: async (query: QueryParams): Promise<Paginated<AlertItem>> => paginate(alerts.filter((item) => matchQuery(item.status, query.status) && matchQuery(item.severity, query.severity) && (query.type ? item.alert_type.includes(String(query.type)) : true)), query),
    patch: async (id: number, body: { action: 'ack' | 'close'; operator?: string }): Promise<AlertItem> => {
      const alert = findById(alerts, id, 'Alert');
      if (body.action === 'ack') Object.assign(alert, { status: 'ack', acked_by: body.operator || 'frontend', acked_at: now, updated_at: now });
      if (body.action === 'close') Object.assign(alert, { status: 'closed', closed_at: now, updated_at: now });
      return clone(alert);
    },
  },
  sync: {
    batches: async (query: QueryParams): Promise<Paginated<SyncBatch>> => paginate(syncBatches, query),
    run: async (): Promise<SyncBatch> => {
      const batch: SyncBatch = { id: Math.max(...syncBatches.map((item) => item.id)) + 1, batch_no: `SYNC-20260628-${String(syncBatches.length + 1).padStart(3, '0')}`, source: 'filing_system', triggered_by: 'frontend', started_at: now, finished_at: null, total_pulled: 0, total_inserted: 0, total_updated: 0, total_skipped: 0, status: 'running', error_message: null, created_at: now, updated_at: now };
      syncBatches.unshift(batch);
      return clone(batch);
    },
    rawFilings: async (query: QueryParams): Promise<Paginated<RawFiling>> => paginate(rawFilings.filter((item) => matchQuery(item.batch_id, query.batch_id)), query),
  },
  reports: {
    weekly: async (week?: string): Promise<UnknownRecord> => getReport('weekly', week),
    monthly: async (month?: string): Promise<UnknownRecord> => getReport('monthly', month),
  },
};
