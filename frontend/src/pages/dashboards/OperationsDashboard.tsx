import { Button, Modal, Spin, message } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { MetricCard } from '../../components/MetricCard';
import { ChartPanel } from '../../components/ChartPanel';
import { ErrorState } from '../../components/ErrorState';
import { JsonBlock } from '../../components/JsonBlock';
import { dashboardsApi, demandsApi, policiesApi, reportsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { money, numberText, percent } from '../../utils/format';

export function OperationsDashboard() {
  const navigate = useNavigate();
  const [report, setReport] = useState<{ title: string; data: unknown } | null>(null);
  const operations = useAsync(() => dashboardsApi.operations(), []);
  const resources = useAsync(() => dashboardsApi.resources({}), []);
  const demands = useAsync(() => demandsApi.list({ page: 1, page_size: 1 }), []);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const loading = operations.loading || resources.loading || demands.loading || policies.loading;
  const error = operations.error || resources.error || demands.error || policies.error;

  async function generateReport(type: 'weekly' | 'monthly') {
    const data = type === 'weekly' ? await reportsApi.weekly() : await reportsApi.monthly();
    setReport({ title: type === 'weekly' ? '周报结果' : '月报结果', data });
    message.success(type === 'weekly' ? '周报已刷新' : '月报已刷新');
  }

  const acceptedPolicies = policies.data?.items.filter((item) => item.status === 'accepted').length || 0;
  const policyRevenue = policies.data?.items.reduce((sum, item) => sum + Number(item.expected_revenue_gain || 0), 0) || 0;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="运营总览"
        description="集中展示需求、资源、策略三大核心域，并提供周报、月报生成入口。"
        actions={<><Button onClick={() => generateReport('weekly')}>生成/刷新周报</Button><Button type="primary" onClick={() => generateReport('monthly')}>生成/刷新月报</Button></>}
      />
      {error ? <ErrorState error={error} onRetry={() => { operations.reload(); resources.reload(); demands.reload(); policies.reload(); }} /> : null}
      <Spin spinning={loading}>
        <div className="metric-grid page-section">
          <MetricCard label="待处理需求" value={operations.data?.pending_demands ?? 0} tone="cyan" onClick={() => navigate('/demands')} />
          <MetricCard label="待审批需求/评估" value={operations.data?.pending_evaluations ?? 0} tone="amber" onClick={() => navigate('/demands')} />
          <MetricCard label="策略条数" value={policies.data?.total ?? 0} tone="purple" onClick={() => navigate('/strategies')} />
          <MetricCard label="今日收益汇总" value={money(operations.data?.revenue_last_24h)} tone="green" onClick={() => navigate('/strategies')} />
          <MetricCard label="平均资源利用率" value={percent(resources.data?.avg_utilization)} tone="red" onClick={() => navigate('/realtime')} />
        </div>
        <div className="dashboard-grid three overview-domains">
          <ChartPanel title="需求概览">
            <button className="domain-card" onClick={() => navigate('/demands')}>
              <strong>{numberText(demands.data?.total)}</strong>
              <span>需求总量</span>
              <small>待处理 {operations.data?.pending_demands ?? 0} · 待审批 {operations.data?.pending_evaluations ?? 0}</small>
            </button>
          </ChartPanel>
          <ChartPanel title="资源概览">
            <button className="domain-card" onClick={() => navigate('/realtime')}>
              <strong>{numberText(resources.data?.total_capacity_tpm)}</strong>
              <span>总容量 TPM</span>
              <small>可用 {numberText(resources.data?.total_available_tpm)} · 利用率 {percent(resources.data?.avg_utilization)}</small>
            </button>
          </ChartPanel>
          <ChartPanel title="策略概览">
            <button className="domain-card" onClick={() => navigate('/strategies')}>
              <strong>{money(policyRevenue)}</strong>
              <span>策略预估收益</span>
              <small>草稿 {operations.data?.draft_policies ?? 0} · 生效 {acceptedPolicies}</small>
            </button>
          </ChartPanel>
        </div>
      </Spin>
      <Modal title={report?.title} open={!!report} footer={null} onCancel={() => setReport(null)} width={820}>
        <JsonBlock value={report?.data || {}} />
      </Modal>
    </>
  );
}
