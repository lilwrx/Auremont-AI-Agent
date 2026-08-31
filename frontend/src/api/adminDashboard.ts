import { api } from "./client";
import type {
  BusinessDashboard,
  LeadStats,
  ManagedLiveSession,
  ObservabilityOverview,
  SaleAccountCreate,
  SalesBoard,
  SaleStatus,
  TraceSummary,
} from "../types/admin";

export const adminDashboardApi = {
  leads: (days = 14, projectId?: string) => {
    const params = new URLSearchParams({ days: String(days) });
    if (projectId) params.set("project_id", projectId);
    return api.get<LeadStats>(`/admin/stats/leads?${params}`);
  },
  business: (days: number, projectId?: string, saleId?: string) => {
    const params = new URLSearchParams({ days: String(days) });
    if (projectId) params.set("project_id", projectId);
    if (saleId) params.set("sale_id", saleId);
    return api.get<BusinessDashboard>(`/admin/stats/business?${params}`);
  },
  sales: (days = 30) => api.get<SalesBoard>(`/admin/sales?days=${days}`),
  createSale: (payload: SaleAccountCreate) => api.post<SaleStatus>("/admin/sales", payload),
  setSaleActive: (saleId: number, isActive: boolean) =>
    api.patch<SaleStatus>(`/admin/sales/${saleId}/active`, { is_active: isActive }),
  reassign: (sessionId: number, saleId: number) =>
    api.post<ManagedLiveSession>("/admin/sales/reassign", { session_id: sessionId, to_sale_id: saleId }),
  observability: (days: number) => api.get<ObservabilityOverview>(`/admin/observability?days=${days}`),
  trace: (runId: string) => api.get<TraceSummary>(`/admin/observability/traces/${runId}`),
};
