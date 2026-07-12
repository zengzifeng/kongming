import { apiClient } from './client';
import type {
  AlertItem,
  ClusterTpmSnapshot,
  ConsumerTpmSnapshot,
  DashboardOperations,
  Demand,
  DemandDetail,
  Evaluation,
  FittingAlgorithm,
  FittingConfig,
  FittingResult,
  FittingResultsResponse,
  JobSchedule,
  MonitorSnapshot,
  Paginated,
  Policy,
  PolicyDetail,
  PolicyReport,
  PolicyRun,
  QueryParams,
  RawFiling,
  ResourceCluster,
  ResourceDashboard,
  RevenueAnalysis,
  RevenueAttribution,
  RevenueDashboard,
  SyncBatch,
  UnknownRecord,
  VendorQuota,
  WatchedCluster,
} from './types';


export const dashboardsApi = {
  operations: (): Promise<DashboardOperations> => apiClient.get('/api/v1/dashboard/operations'),
  customers: (customerId?: number): Promise<UnknownRecord> =>
    apiClient.get('/api/v1/dashboard/customers', { customer_id: customerId }),
  management: (range = '7d'): Promise<UnknownRecord> =>
    apiClient.get('/api/v1/dashboard/management', { range }),
  resources: (query: { gpu_model?: string; datacenter?: string; cluster_name?: string; deployed_model?: string }): Promise<ResourceDashboard> =>
    apiClient.get('/api/v1/dashboard/resources', query),
  updateClusterResource: (body: {
    cluster_name: string;
    machine_count?: number;
    deployed_model: string;
    provider?: string;
    tpm_per_machine_w: number;
    current_tpm_w?: number;

  }): Promise<ResourceCluster> => apiClient.patch('/api/v1/dashboard/resources/clusters', body),
};

export const demandsApi = {
  list: (query: QueryParams): Promise<Paginated<Demand>> => apiClient.get('/api/v1/demands', query),
  detail: (id: number): Promise<DemandDetail> => apiClient.get(`/api/v1/demands/${id}`),
  patch: (id: number, body: UnknownRecord): Promise<Demand> => apiClient.patch(`/api/v1/demands/${id}`, body),
  evaluate: (id: number, force = false): Promise<Evaluation> =>
    apiClient.post(`/api/v1/demands/${id}/evaluate`, { force }),
};

export const evaluationsApi = {
  list: (query: QueryParams): Promise<Paginated<Evaluation>> => apiClient.get('/api/v1/evaluations', query),
  detail: (id: number): Promise<Evaluation> => apiClient.get(`/api/v1/evaluations/${id}`),
  approve: (id: number, body: { operator: string; comment?: string }): Promise<Evaluation> =>
    apiClient.post(`/api/v1/evaluations/${id}/approve`, body),
  reject: (id: number, body: { operator: string; reason: string }): Promise<Evaluation> =>
    apiClient.post(`/api/v1/evaluations/${id}/reject`, body),
};

export const policiesApi = {
  createRun: (body: { algorithm: string; demand_ids?: number[]; demand_id?: number; params?: UnknownRecord | null }): Promise<PolicyRun> =>
    apiClient.post('/api/v1/policy-runs', body),
  runs: (query: QueryParams): Promise<Paginated<PolicyRun>> => apiClient.get('/api/v1/policy-runs', query),
  runDetail: (id: number): Promise<PolicyRun> => apiClient.get(`/api/v1/policy-runs/${id}`),
  snapshot: (id: number): Promise<UnknownRecord> => apiClient.get(`/api/v1/policy-runs/${id}/snapshot`),
  list: (query: QueryParams): Promise<Paginated<Policy>> => apiClient.get('/api/v1/policies', query),
  detail: (id: number): Promise<PolicyDetail> => apiClient.get(`/api/v1/policies/${id}`),
  report: (id: number): Promise<PolicyReport> => apiClient.get(`/api/v1/policies/${id}/report`),
  patch: (id: number, body: UnknownRecord): Promise<Policy> => apiClient.patch(`/api/v1/policies/${id}`, body),

  accept: (id: number, body: { operator: string; effective_from?: string; comment?: string }): Promise<Policy> =>
    apiClient.post(`/api/v1/policies/${id}/accept`, body),
  cancel: (id: number, body: { operator: string; reason: string }): Promise<Policy> =>
    apiClient.post(`/api/v1/policies/${id}/cancel`, body),
  recalculate: (id: number, params?: UnknownRecord | null): Promise<PolicyRun> =>
    apiClient.post(`/api/v1/policies/${id}/recalculate`, { operator: 'frontend', params }),
  auditLogs: (id: number): Promise<UnknownRecord[]> => apiClient.get(`/api/v1/policies/${id}/audit-logs`),
};

export const revenueApi = {
  dashboard: (): Promise<RevenueDashboard> => apiClient.get('/api/v1/revenue/dashboard'),
  attributions: (query: QueryParams): Promise<Paginated<RevenueAttribution>> =>
    apiClient.get('/api/v1/revenue/attributions', query),
  policyRevenue: (policyId: number): Promise<UnknownRecord> =>
    apiClient.get(`/api/v1/revenue/policies/${policyId}`),
  analysis: (): Promise<RevenueAnalysis> => apiClient.get('/api/v1/revenue/analysis'),
  archiveAnalysis: (policyId: number, body: { operator: string; reason: string }): Promise<RevenueAnalysis> =>
    apiClient.post(`/api/v1/revenue/analysis/${policyId}/archive`, body),
};

export const vendorsApi = {
  quotas: (query: QueryParams): Promise<Paginated<VendorQuota>> =>
    apiClient.get('/api/v1/vendors/quotas', query),
};

export const monitorApi = {
  clusterTpm: (): Promise<MonitorSnapshot<ClusterTpmSnapshot>> => apiClient.get('/api/v1/monitor/cluster-tpm'),
  consumerTpm: (query: { ai_consumer?: string; ai_model?: string } = {}): Promise<MonitorSnapshot<ConsumerTpmSnapshot>> =>
    apiClient.get('/api/v1/monitor/consumer-tpm', query),
};

export const fittingsApi = {
  algorithms: (): Promise<FittingAlgorithm[]> => apiClient.get('/api/v1/fittings/algorithms'),
  configs: (query: QueryParams = {}): Promise<FittingConfig[]> => apiClient.get('/api/v1/fittings/configs', query),
  results: (query: QueryParams = {}): Promise<FittingResultsResponse> => apiClient.get('/api/v1/fittings/results', query),
};

export const jobsApi = {
  list: (): Promise<JobSchedule[]> => apiClient.get('/api/v1/jobs'),
  patch: (jobName: string, body: Partial<JobSchedule>): Promise<JobSchedule> => apiClient.patch(`/api/v1/jobs/${jobName}`, body),
};

export const watchedClustersApi = {
  list: (includeDisabled = false): Promise<WatchedCluster[]> => apiClient.get('/api/v1/watched-clusters', { include_disabled: includeDisabled }),
  create: (body: { cluster_name: string; enabled?: boolean; sort_order?: number }): Promise<WatchedCluster> => apiClient.post('/api/v1/watched-clusters', body),
  patch: (id: number, body: Partial<WatchedCluster>): Promise<WatchedCluster> => apiClient.patch(`/api/v1/watched-clusters/${id}`, body),
  delete: (id: number): Promise<{ deleted: number }> => apiClient.delete(`/api/v1/watched-clusters/${id}`),
};

export const alertsApi = {

  list: (query: QueryParams): Promise<Paginated<AlertItem>> => apiClient.get('/api/v1/alerts', query),
  patch: (id: number, body: { action: 'ack' | 'close'; operator?: string }): Promise<AlertItem> =>
    apiClient.patch(`/api/v1/alerts/${id}`, body),
};

export const rawFilingsApi = {
  list: (query: QueryParams): Promise<Paginated<RawFiling>> => apiClient.get('/api/v1/raw-filings', query),
};


export const syncApi = {
  list: (query: QueryParams): Promise<Paginated<SyncBatch>> => apiClient.get('/api/v1/sync-batches', query),
  batches: (query: QueryParams): Promise<Paginated<SyncBatch>> => apiClient.get('/api/v1/sync-batches', query),
  trigger: (reason = 'manual'): Promise<SyncBatch> => apiClient.post('/api/v1/sync-batches/run', { reason }),
  run: (reason = 'manual'): Promise<SyncBatch> => apiClient.post('/api/v1/sync-batches/run', { reason }),
  detail: (id: number): Promise<SyncBatch> => apiClient.get(`/api/v1/sync-batches/${id}`),
  filings: (query: QueryParams): Promise<Paginated<RawFiling>> => apiClient.get('/api/v1/raw-filings', query),
  rawFilings: (query: QueryParams): Promise<Paginated<RawFiling>> => apiClient.get('/api/v1/raw-filings', query),
};


export const syncBatchesApi = syncApi;


export const reportsApi = {
  weekly: (week?: string): Promise<UnknownRecord> => apiClient.get('/api/v1/reports/weekly', { week }),
  monthly: (month?: string): Promise<UnknownRecord> => apiClient.get('/api/v1/reports/monthly', { month }),
};

