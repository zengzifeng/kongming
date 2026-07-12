import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { EmptyState } from '../../components/EmptyState';
import { dashboardsApi, fittingsApi, policiesApi, revenueApi, watchedClustersApi } from '../../api/kongming';
import type { FittingResult, Policy, PolicyDetail, ResourceCluster, RevenueAnalysisItem } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';
import { isWatchedCluster, watchedClusterNames } from '../../utils/watchedClusters';

const clusterBarColors = ['#27d7ff', '#5dffb2', '#9b8cff', '#6aa7ff'];

function timeLabel(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function runtimeRows(result?: FittingResult) {
  return (result?.series_json || []).map(([ts, value], index, arr) => {
    const forecast = Number(value || 0);
    const previous = index > 0 ? Number(arr[index - 1]?.[1] || forecast) : forecast;
    return { time: timeLabel(ts), dayBefore: previous, yesterday: forecast, forecast };
  });
}

function redundantRow(cluster: ResourceCluster) {
  return { cluster: cluster.cluster_name, machines: Number(cluster.idle_redundant_machines ?? cluster.current_redundant_machines ?? 0) };
}

function clusterPlanFromResource(cluster: ResourceCluster) {
  return {
    cluster: cluster.cluster_name,
    customer: cluster.primary_customer || '-',
    move: cluster.deployed_model,
    watermark: `${Math.round(Number(cluster.cluster_utilization || 0) * 100)}%`,
    redundant: Number(cluster.idle_redundant_machines ?? cluster.current_redundant_machines ?? 0),
  };
}

function benefitRows(policies: Policy[]) {
  return policies.slice(0, 7).map((item) => {
    const total = Number(item.expected_off_peak_gain || item.expected_revenue_gain || 0);
    return { day: item.policy_no, baseGain: 0, shiftGain: total, total, target: total };
  });
}

function revenueRows(items: RevenueAnalysisItem[], policies: Policy[]) {
  const allowed = new Set(policies.map((item) => item.id));
  return items.filter((item) => allowed.has(item.policy_id)).slice(-7).map((item) => ({
    day: item.policy_no,
    expected: Number(item.expected_revenue_gain || 0),
    actual: Number(item.actual_revenue_gain || 0),
    gap: Number(item.revenue_gap || 0),
  }));
}

const axisTick = { fill: '#7898a8', fontSize: 12 };
const tooltipStyle = {
  backgroundColor: 'rgba(7, 16, 24, 0.96)',
  border: '1px solid rgba(39, 215, 255, 0.28)',
  borderRadius: 8,
  color: '#e6f7ff',
};

function pickPolicies(policies: Policy[], key: string) {
  return policies.filter((item) => item.algorithm === key || JSON.stringify(item.summary_json || {}).includes(key));
}

function tpmTick(value: number | string) {
  if (typeof value !== 'number') return value;
  return value === 0 ? '0' : `${Math.round(value / 1000)}K`;
}

function revenueTick(value: number | string) {
  if (typeof value !== 'number') return value;
  return value === 0 ? '0k' : `${Math.round(value / 1000)}k`;
}

function numberTooltip(value: number | string) {
  return typeof value === 'number' ? numberText(value) : value;
}

function moneyTooltip(value: number | string) {
  return typeof value === 'number' ? money(value) : value;
}

export function IdleDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Policy | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedCluster, setSelectedCluster] = useState('');
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const resources = useAsync(() => dashboardsApi.resources({}), []);
  const fitting = useAsync(() => fittingsApi.results({ level: 'cluster', period: 'idle', page_size: 100 }), []);
  const revenue = useAsync(() => revenueApi.analysis(), []);
  const watchedClusters = useAsync(() => watchedClustersApi.list(), []);
  const watchedNames = watchedClusterNames(watchedClusters.data);
  const resourceClusters = (resources.data?.clusters || []).filter((cluster) => isWatchedCluster(cluster.cluster_name, watchedNames));
  const fittingItems = (fitting.data?.items || []).filter((item) => isWatchedCluster(item.cluster_name, watchedNames));
  const idlePolicies = useMemo(() => pickPolicies(policies.data?.items || [], 'off_peak'), [policies.data?.items]);
  const clusterOptions = useMemo(() => fittingItems.map((item) => ({ label: item.cluster_name || item.model_name, value: item.cluster_name || item.model_name })), [fittingItems]);
  const selectedFit = fittingItems.find((item) => (item.cluster_name || item.model_name) === selectedCluster) || fittingItems[0];
  const selectedRuntime = runtimeRows(selectedFit);
  const redundantMachines = resourceClusters.map(redundantRow).slice(0, 6);
  const clusterPlans = resourceClusters.map(clusterPlanFromResource).slice(0, 6);
  const benefitBars = benefitRows(idlePolicies);
  const revenueTrend = revenueRows(revenue.data?.items || [], idlePolicies);
  const totalGain = benefitBars.reduce((sum, item) => sum + item.total, 0);

  useEffect(() => {
    if ((!selectedCluster || !clusterOptions.some((option) => option.value === selectedCluster)) && clusterOptions[0]) setSelectedCluster(clusterOptions[0].value);
  }, [selectedCluster, clusterOptions]);

  async function createRun() {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: 'off_peak', params: { template: '闲时策略' } });
      message.success('闲时策略生成已提交');
      setCreateOpen(false);
      await policies.reload();
    } finally {
      setSubmitting(false);
    }
  }

  async function openDetail(policy: Policy) {
    setSelected(policy);
    setDetail(await policiesApi.detail(policy.id));
  }

  async function accept(policy: Policy) {
    await policiesApi.accept(policy.id, { operator: 'frontend' });
    message.success('策略已生效');
    await policies.reload();
    if (selected?.id === policy.id) await openDetail(policy);
  }

  async function abandon(policy: Policy) {
    await policiesApi.cancel(policy.id, { operator: 'frontend', reason: '前端放弃策略' });
    message.success('策略已放弃');
    setSelected(null);
    setDetail(null);
    await policies.reload();
  }

  async function patch(values: { summary_json?: string; constraints_json?: string; expected_revenue_gain?: string; effective_from?: string; effective_to?: string }) {
    if (!selected) return;
    setSubmitting(true);
    try {
      await policiesApi.patch(selected.id, {
        summary_json: parseJsonObject(values.summary_json),
        constraints_json: parseJsonObject(values.constraints_json),
        expected_revenue_gain: values.expected_revenue_gain ? Number(values.expected_revenue_gain) : undefined,
        effective_from: values.effective_from || undefined,
        effective_to: values.effective_to || undefined,
      });
      message.success('策略已修改');
      setEditOpen(false);
      await policies.reload();
      await openDetail(selected);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Idle" title="闲时看板" description="展示夜间集群跑量、冗余机器台数、调整建议、收益预估与历史收益偏差。" actions={<Button type="primary" onClick={() => setCreateOpen(true)}>生成闲时策略</Button>} />
      <Spin spinning={policies.loading || resources.loading || fitting.loading || revenue.loading || watchedClusters.loading}>
        <div className="idle-dashboard-grid page-section">
          <section className="wire-card dashboard-panel-wide idle-runtime-card">
            <div className="idle-card-head">
              <div className="wire-card-title">闲时跑量预估</div>
              <label className="idle-cluster-picker">
                <span>集群:</span>
                <Select value={selectedCluster} options={clusterOptions} onChange={setSelectedCluster} />
              </label>
            </div>
            <div className="resource-chart tall-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={selectedRuntime} margin={{ top: 6, right: 8, left: 4, bottom: 2 }}>
                  <CartesianGrid stroke="rgba(230, 247, 255, 0.3)" strokeDasharray="2 4" />
                  <XAxis dataKey="time" tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} />
                  <YAxis ticks={[0, 150000, 300000, 450000, 600000]} domain={[0, 600000]} tickFormatter={tpmTick} tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} width={48} />
                  <Tooltip contentStyle={tooltipStyle} formatter={numberTooltip} labelStyle={{ color: '#dff8ff' }} />
                  <Legend verticalAlign="bottom" height={34} iconType="line" wrapperStyle={{ color: '#9fbfcb', paddingTop: 12 }} />
                  <Line type="monotone" dataKey="dayBefore" name="前日闲时实跑" stroke="#27d7ff" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="yesterday" name="昨日闲时实跑" stroke="#5dffb2" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="forecast" name="明日移动平均预测" stroke="#ffb347" strokeWidth={2} dot={false} strokeDasharray="5 4" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card dashboard-panel-wide">
            <div className="wire-card-title">每个集群冗余机器台数</div>
            <div className="resource-chart tall-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={redundantMachines} margin={{ top: 6, right: 8, left: 4, bottom: 2 }}>
                  <CartesianGrid stroke="rgba(230, 247, 255, 0.3)" strokeDasharray="2 4" />
                  <XAxis dataKey="cluster" tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} />
                  <YAxis ticks={[0, 5, 10, 15, 20]} domain={[0, 20]} tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} width={34} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: '#dff8ff' }} />
                  <Bar dataKey="machines" name="冗余机器台数" radius={[8, 8, 3, 3]}>
                    {redundantMachines.map((_, index) => <Cell key={index} fill={clusterBarColors[index % clusterBarColors.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card dashboard-panel-wide idle-adjustment-card">
            <div className="wire-card-title">调整方案建议</div>
            <Table size="small" rowKey="cluster" dataSource={clusterPlans} pagination={false} columns={[
              { title: '集群', dataIndex: 'cluster' },
              { title: '承接客户', dataIndex: 'customer' },
              { title: '调整方案', dataIndex: 'move' },
              { title: '水位线', dataIndex: 'watermark' },
              { title: '冗余台数', dataIndex: 'redundant', render: numberText },
            ]} />
            {idlePolicies.length ? <Table<Policy> className="inner-table" size="small" rowKey="id" dataSource={idlePolicies} pagination={{ pageSize: 4 }} scroll={{ x: 'max-content' }} onRow={(record) => ({ onClick: () => openDetail(record) })} columns={[{ title: '策略编号', dataIndex: 'policy_no' }, { title: '算法', dataIndex: 'algorithm' }, { title: '预估收益', dataIndex: 'expected_revenue_gain', render: money }, { title: '生效时间', dataIndex: 'effective_from', render: dateText }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} /> : <EmptyState />}
          </section>

          <section className="wire-card dashboard-panel-wide idle-revenue-panel">
            <div className="wire-card-title">预估收益</div>
            <div className="circle-metric solo-metric"><strong>{money(totalGain)}</strong><span>闲时总收益</span></div>
            <div className="resource-chart short-chart">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={benefitBars} margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(230, 247, 255, 0.3)" strokeDasharray="2 4" />
                  <XAxis dataKey="day" tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} />
                  <YAxis ticks={[0, 6000, 11000, 17000, 22000]} domain={[0, 22000]} tickFormatter={revenueTick} tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} width={42} />
                  <Tooltip contentStyle={tooltipStyle} formatter={moneyTooltip} labelStyle={{ color: '#dff8ff' }} />
                  <Bar dataKey="baseGain" stackId="gain" name="基础收益" fill="#27d7ff" radius={[0, 0, 4, 4]} />
                  <Bar dataKey="shiftGain" stackId="gain" name="闲时增益" fill="#5dffb2" radius={[6, 6, 0, 0]} />
                  <Line type="monotone" dataKey="target" name="收益趋势" stroke="#ffb347" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card idle-history-panel">
            <div className="wire-card-title">历史收益累计及实际收益偏差分析</div>
            <div className="resource-chart short-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={revenueTrend} margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(230, 247, 255, 0.22)" strokeDasharray="2 4" />
                  <XAxis dataKey="day" tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} />
                  <YAxis tick={axisTick} axisLine={{ stroke: 'rgba(230, 247, 255, 0.22)' }} tickLine={false} width={44} />
                  <Tooltip contentStyle={tooltipStyle} formatter={moneyTooltip} labelStyle={{ color: '#dff8ff' }} />
                  <Line type="monotone" dataKey="expected" name="预估收益" stroke="#27d7ff" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="actual" name="实际收益" stroke="#5dffb2" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="gap" name="收益偏差" stroke="#ff5f6d" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <Table size="small" rowKey="day" dataSource={revenueTrend.slice(-4)} pagination={false} columns={[{ title: '日期', dataIndex: 'day' }, { title: '预估', dataIndex: 'expected', render: money }, { title: '实际', dataIndex: 'actual', render: money }, { title: '偏差', dataIndex: 'gap', render: money }]} />
          </section>
        </div>
      </Spin>

      <Modal title="生成闲时策略" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form layout="vertical" onFinish={createRun} initialValues={{ template: 'off_peak' }}><Form.Item name="template" label="策略模板"><Select disabled options={[{ label: '闲时策略', value: 'off_peak' }]} /></Form.Item><Button loading={submitting} type="primary" htmlType="submit" block>生成</Button></Form>
      </Modal>
      <Drawer title="闲时策略详情" open={!!selected} onClose={() => { setSelected(null); setDetail(null); }} width={720}>
        {selected && <Space style={{ marginBottom: 16 }}><Button onClick={() => setEditOpen(true)}>修改</Button><Button type="primary" disabled={selected.status !== 'draft'} onClick={() => accept(selected)}>生效</Button><Button danger disabled={selected.status === 'cancelled'} onClick={() => abandon(selected)}>放弃</Button></Space>}
        {detail && <><Descriptions bordered size="small" column={2}><Descriptions.Item label="策略号">{detail.policy.policy_no}</Descriptions.Item><Descriptions.Item label="状态"><StatusTag value={detail.policy.status} /></Descriptions.Item><Descriptions.Item label="算法">{detail.policy.algorithm}</Descriptions.Item><Descriptions.Item label="预估收益">{money(detail.policy.expected_revenue_gain)}</Descriptions.Item><Descriptions.Item label="生效时间">{dateText(detail.policy.effective_from)}</Descriptions.Item><Descriptions.Item label="结束时间">{dateText(detail.policy.effective_to)}</Descriptions.Item></Descriptions><JsonBlock value={{ summary: detail.policy.summary_json, constraints: detail.policy.constraints_json, actions: detail.actions }} /></>}
      </Drawer>
      <Modal title="修改闲时策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
        <Form layout="vertical" onFinish={patch} initialValues={{ summary_json: JSON.stringify(detail?.policy.summary_json || {}, null, 2), constraints_json: JSON.stringify(detail?.policy.constraints_json || {}, null, 2), expected_revenue_gain: String(detail?.policy.expected_revenue_gain || '') }}><Form.Item name="summary_json" label="策略摘要 JSON"><Input.TextArea rows={4} /></Form.Item><Form.Item name="constraints_json" label="约束 JSON"><Input.TextArea rows={4} /></Form.Item><Form.Item name="expected_revenue_gain" label="预估收益"><Input /></Form.Item><Form.Item name="effective_from" label="生效时间"><Input placeholder="ISO 时间" /></Form.Item><Form.Item name="effective_to" label="结束时间"><Input placeholder="ISO 时间" /></Form.Item><Button loading={submitting} type="primary" htmlType="submit" block>保存</Button></Form>
      </Modal>
    </>
  );
}
