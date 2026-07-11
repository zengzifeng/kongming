import { apiClient } from './client';
import { mockApi } from './mockData';
import type { Paginated, QueryParams, ResourceCluster, ResourceDashboard, VendorQuota } from './types';

export const dashboardsApi = {
  ...mockApi.dashboards,
  resources: async (query: { gpu_model?: string; datacenter?: string; cluster_name?: string; deployed_model?: string }): Promise<ResourceDashboard> => {
    try {
      return await apiClient.get<ResourceDashboard>('/api/v1/dashboard/resources', query);
    } catch {
      return mockApi.dashboards.resources(query);
    }
  },
  updateClusterResource: async (body: {
    cluster_name: string;
    deployed_model: string;
    tpm_per_machine_w: number;
    machine_count?: number;
    current_tpm_w?: number;
    provider?: string;
  }): Promise<ResourceCluster> => apiClient.patch<ResourceCluster>('/api/v1/dashboard/resources/clusters', body),
};

export const demandsApi = mockApi.demands;

export const evaluationsApi = mockApi.evaluations;

export const policiesApi = mockApi.policies;

export const revenueApi = mockApi.revenue;

export const vendorsApi = {
  ...mockApi.vendors,
  quotas: async (query: QueryParams): Promise<Paginated<VendorQuota>> => {
    try {
      return await apiClient.get<Paginated<VendorQuota>>('/api/v1/vendors/quotas', query);
    } catch {
      return mockApi.vendors.quotas(query);
    }
  },
};

export const alertsApi = mockApi.alerts;

export const syncApi = mockApi.sync;

export const reportsApi = mockApi.reports;
