import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
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

function buildRuntimeRows(results: FittingResult[]) {
  const rows: Record<string, string | number>[] = [];
  results.slice(0, 3).forEach((result, resultIndex) => {
    const key = `cluster${String.fromCharCode(65 + resultIndex)}`;
    (result.series_json || []).forEach(([ts, value], pointIndex) => {
      const row = rows[pointIndex] || { time: timeLabel(ts) };
      row[key] = Number(value || 0);
      rows[pointIndex] = row;
    });
  });
  return rows.map((row) => ({ ...row, fit: Math.round((Number(row.clusterA || 0) + Number(row.clusterB || 0) + Number(row.clusterC || 0)) / 3) }));
}

function redundantRow(cluster: ResourceCluster) {
  return { cluster: cluster.cluster_name, machines: Number(cluster.busy_redundant_machines ?? cluster.current_redundant_machines ?? 0) };
}

function clusterPlanFromResource(cluster: ResourceCluster) {
  return {
    cluster: cluster.cluster_name,
    customer: cluster.primary_customer || '-',
    move: cluster.deployed_model,
    watermark: `${Math.round(Number(cluster.cluster_utilization || 0) * 100)}%`,
    redundant: Number(cluster.busy_redundant_machines ?? cluster.current_redundant_machines ?? 0),
  };
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

function pickPolicies(policies: Policy[], key: string) {
  return policies.filter((item) => item.algorithm === key || JSON.stringify(item.summary_json || {}).includes(key));
}

export function BusyDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Policy | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const resources = useAsync(() => dashboardsApi.resources({}), []);
  const fitting = useAsync(() => fittingsApi.results({ level: 'cluster', period: 'busy', page_size: 100 }), []);
  const revenue = useAsync(() => revenueApi.analysis(), []);
  const watchedClusters = useAsync(() => watchedClustersApi.list(), []);
  const watchedNames = watchedClusterNames(watchedClusters.data);
  const resourceClusters = (resources.data?.clusters || []).filter((cluster) => isWatchedCluster(cluster.cluster_name, watchedNames));
  const fittingItems = (fitting.data?.items || []).filter((item) => isWatchedCluster(item.cluster_name, watchedNames));
  const busyPolicies = useMemo(() => pickPolicies(policies.data?.items || [], 'off_peak'), [policies.data?.items]);
  const dayRuntime = buildRuntimeRows(fittingItems);
  const redundantMachines = resourceClusters.map(redundantRow).slice(0, 6);
  const clusterPlans = resourceClusters.map(clusterPlanFromResource).slice(0, 6);
  const revenueBars = busyPolicies.map((item) => ({ name: item.policy_no, gain: Number(item.expected_revenue_gain || 0) }));
  const revenueTrend = revenueRows(revenue.data?.items || [], busyPolicies);
  const totalGain = revenueBars.reduce((sum, item) => sum + item.gain, 0);

  async function createRun() {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: 'off_peak', params: { template: '忙时策略' } });
      message.success('忙时策略生成已提交');
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
      <PageHeader eyebrow="Busy" title="忙时看板" description="展示白天集群跑量、冗余机器台数、调整建议、收益预估与历史收益偏差。" actions={<Button type="primary" onClick={() => setCreateOpen(true)}>生成忙时策略</Button>} />
      <Spin spinning={policies.loading || resources.loading || fitting.loading || revenue.loading || watchedClusters.loading}>
        <div className="busy-board page-section">
          <section className="wire-card busy-panel">
            <div className="wire-card-title">集群维度白天跑量</div>
            <div className="resource-chart busy-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={dayRuntime}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="time" /><YAxis domain={[0, 1000]} /><Tooltip /><Line type="monotone" dataKey="clusterA" name="Cluster-A" stroke="#27d7ff" strokeWidth={2} dot={{ r: 3 }} /><Line type="monotone" dataKey="clusterB" name="Cluster-B" stroke="#5dffb2" strokeWidth={2} dot={{ r: 3 }} /><Line type="monotone" dataKey="clusterC" name="Cluster-C" stroke="#9b8cff" strokeWidth={2} dot={{ r: 3 }} /><Line type="monotone" dataKey="fit" name="白天拟合" stroke="#ffb347" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} /></LineChart></ResponsiveContainer></div>
          </section>

          <section className="wire-card busy-panel">
            <div className="wire-card-title">每个集群冗余机器台数</div>
            <div className="resource-chart busy-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={redundantMachines}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="cluster" /><YAxis domain={[0, 8]} /><Tooltip /><Bar dataKey="machines" name="冗余机器台数" radius={[10, 10, 4, 4]}>{redundantMachines.map((_, index) => <Cell key={index} fill={clusterBarColors[index % clusterBarColors.length]} />)}</Bar></BarChart></ResponsiveContainer></div>
          </section>

          <section className="wire-card busy-panel busy-plan-panel">
            <div className="wire-card-title">调整方案建议</div>
            <Table className="busy-table" size="small" rowKey="cluster" dataSource={clusterPlans} pagination={false} columns={[{ title: '集群', dataIndex: 'cluster' }, { title: '承接客户', dataIndex: 'customer' }, { title: '调整方案', dataIndex: 'move' }, { title: '水位线', dataIndex: 'watermark' }, { title: '冗余', dataIndex: 'redundant', render: numberText }]} />
            {busyPolicies.length ? <Table<Policy> className="inner-table busy-table" size="small" rowKey="id" dataSource={busyPolicies} pagination={{ pageSize: 4, simple: true }} scroll={{ x: 'max-content' }} onRow={(record) => ({ onClick: () => openDetail(record) })} columns={[{ title: '策略编号', dataIndex: 'policy_no' }, { title: '算法', dataIndex: 'algorithm' }, { title: '预估收益', dataIndex: 'expected_revenue_gain', render: money }, { title: '生效时间', dataIndex: 'effective_from', render: dateText }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} /> : <EmptyState />}
          </section>

          <section className="wire-card busy-panel busy-revenue-panel">
            <div className="wire-card-title">预估收益</div>
            <div className="circle-metric solo-metric"><strong>{money(totalGain)}</strong><span>忙时预估收益</span></div>
            <div className="resource-chart busy-revenue-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={revenueBars}><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="gain" name="预估收益" fill="#ffb347" /></BarChart></ResponsiveContainer></div>
          </section>

          <section className="wire-card busy-panel busy-history-panel">
            <div className="wire-card-title">历史收益累计及实际收益偏差分析</div>
            <div className="resource-chart busy-history-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={revenueTrend}><XAxis dataKey="day" /><YAxis /><Tooltip /><Line type="monotone" dataKey="expected" name="预估收益" stroke="#27d7ff" /><Line type="monotone" dataKey="actual" name="实际收益" stroke="#5dffb2" /><Line type="monotone" dataKey="gap" name="收益偏差" stroke="#ff5f6d" /></LineChart></ResponsiveContainer></div>
            <Table className="busy-table" size="small" rowKey="day" dataSource={revenueTrend.slice(-4)} pagination={false} columns={[{ title: '日期', dataIndex: 'day' }, { title: '预估', dataIndex: 'expected', render: money }, { title: '实际', dataIndex: 'actual', render: money }, { title: '偏差', dataIndex: 'gap', render: money }]} />
          </section>
        </div>
      </Spin>

      <Modal title="生成忙时策略" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form layout="vertical" onFinish={createRun} initialValues={{ template: 'off_peak' }}><Form.Item name="template" label="策略模板"><Select disabled options={[{ label: '忙时策略', value: 'off_peak' }]} /></Form.Item><Button loading={submitting} type="primary" htmlType="submit" block>生成</Button></Form>
      </Modal>
      <Drawer title="忙时策略详情" open={!!selected} onClose={() => { setSelected(null); setDetail(null); }} width={720}>
        {selected && <Space style={{ marginBottom: 16 }}><Button onClick={() => setEditOpen(true)}>修改</Button><Button type="primary" disabled={selected.status !== 'draft'} onClick={() => accept(selected)}>生效</Button><Button danger disabled={selected.status === 'cancelled'} onClick={() => abandon(selected)}>放弃</Button></Space>}
        {detail && <><Descriptions bordered size="small" column={2}><Descriptions.Item label="策略号">{detail.policy.policy_no}</Descriptions.Item><Descriptions.Item label="状态"><StatusTag value={detail.policy.status} /></Descriptions.Item><Descriptions.Item label="算法">{detail.policy.algorithm}</Descriptions.Item><Descriptions.Item label="预估收益">{money(detail.policy.expected_revenue_gain)}</Descriptions.Item><Descriptions.Item label="生效时间">{dateText(detail.policy.effective_from)}</Descriptions.Item><Descriptions.Item label="结束时间">{dateText(detail.policy.effective_to)}</Descriptions.Item></Descriptions><JsonBlock value={{ summary: detail.policy.summary_json, constraints: detail.policy.constraints_json, actions: detail.actions }} /></>}
      </Drawer>
      <Modal title="修改忙时策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
        <Form layout="vertical" onFinish={patch} initialValues={{ summary_json: JSON.stringify(detail?.policy.summary_json || {}, null, 2), constraints_json: JSON.stringify(detail?.policy.constraints_json || {}, null, 2), expected_revenue_gain: String(detail?.policy.expected_revenue_gain || '') }}><Form.Item name="summary_json" label="策略摘要 JSON"><Input.TextArea rows={4} /></Form.Item><Form.Item name="constraints_json" label="约束 JSON"><Input.TextArea rows={4} /></Form.Item><Form.Item name="expected_revenue_gain" label="预估收益"><Input /></Form.Item><Form.Item name="effective_from" label="生效时间"><Input placeholder="ISO 时间" /></Form.Item><Form.Item name="effective_to" label="结束时间"><Input placeholder="ISO 时间" /></Form.Item><Button loading={submitting} type="primary" htmlType="submit" block>保存</Button></Form>
      </Modal>
    </>
  );
}
