import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { dashboardsApi, monitorApi, policiesApi, revenueApi, watchedClustersApi } from '../../api/kongming';
import type { ClusterTpmSnapshot, Policy, PolicyDetail, ResourceCluster, RevenueAnalysisItem } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';
import { isWatchedCluster, watchedClusterNames } from '../../utils/watchedClusters';

function timeLabel(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function buildPeakRuntime(items: ClusterTpmSnapshot[]) {
  const row: Record<string, string | number> = { time: items[0] ? timeLabel(items[0].data_time) : '-' };
  items.slice(0, 4).forEach((item, index) => { row[`cluster${String.fromCharCode(65 + index)}`] = Number(item.tpm || 0); });
  row.watermark = Math.max(0, ...items.slice(0, 4).map((item) => Number(item.node_avg_tpm || 0)));
  return items.length ? [row] : [];
}

function shavingResource(cluster: ResourceCluster, policies: Policy[]) {
  const gain = policies.reduce((sum, item) => sum + Number(item.expected_peak_shaving_gain || item.expected_revenue_gain || 0), 0) / Math.max(policies.length, 1);
  return { cluster: cluster.cluster_name, redundant: Number(cluster.current_redundant_tpm || 0), gain };
}

function clusterAction(cluster: ResourceCluster) {
  return { cluster: cluster.cluster_name, move: cluster.deployed_model, watermark: `${numberText(cluster.current_tpm || 0)} TPM`, protected: cluster.primary_customer || '-' };
}

function forecastRow(cluster: ResourceCluster) {
  const before = Number(cluster.current_tpm || 0) + Number(cluster.current_redundant_tpm || 0);
  const after = Number(cluster.current_tpm || 0);
  return {
    date: cluster.cluster_name,
    before,
    after,
    shaved: Math.max(before - after, 0),
    beforeMachines: Number(cluster.machine_count || 0),
    afterMachines: Math.max(Number(cluster.machine_count || 0) - Number(cluster.current_redundant_machines || 0), 0),
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

export function PeakShavingDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Policy | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const resources = useAsync(() => dashboardsApi.resources({}), []);
  const clusterTpm = useAsync(() => monitorApi.clusterTpm(), []);
  const revenue = useAsync(() => revenueApi.analysis(), []);
  const watchedClusters = useAsync(() => watchedClustersApi.list(), []);
  const watchedNames = watchedClusterNames(watchedClusters.data);
  const peakPolicies = useMemo(() => pickPolicies(policies.data?.items || [], 'peak_shaving'), [policies.data?.items]);
  const resourceClusters = (resources.data?.clusters || []).filter((cluster) => isWatchedCluster(cluster.cluster_name, watchedNames));
  const clusterTpmItems = (clusterTpm.data?.items || []).filter((item) => isWatchedCluster(item.cluster_name, watchedNames));
  const peakRuntime = buildPeakRuntime(clusterTpmItems);
  const shavingResources = resourceClusters.map((cluster) => shavingResource(cluster, peakPolicies)).slice(0, 6);
  const clusterActions = resourceClusters.map(clusterAction).slice(0, 6);
  const shavingForecast = resourceClusters.map(forecastRow).slice(0, 6);
  const forecastPolicies = peakPolicies.map((policy) => ({
    policyId: policy.id,
    policyNo: policy.policy_no,
    expectedGain: Number(policy.expected_peak_shaving_gain || policy.expected_revenue_gain || 0),
    status: policy.status,
  }));
  const revenueTrend = revenueRows(revenue.data?.items || [], peakPolicies);
  const displayGain = forecastPolicies.reduce((sum, item) => sum + item.expectedGain, 0);
  const resourceGain = shavingResources.reduce((sum, item) => sum + item.gain, 0);

  async function createRun() {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: 'peak_shaving', params: { template: '削峰策略' } });
      message.success('削峰策略生成已提交');
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
      <PageHeader eyebrow="Peak Shaving" title="削峰看板" description="按照削峰逻辑展示集群实跑、水位线建议、削峰后资源冗余与收益。" actions={<Button type="primary" onClick={() => setCreateOpen(true)}>生成削峰策略</Button>} />
      <Spin spinning={policies.loading || resources.loading || clusterTpm.loading || revenue.loading || watchedClusters.loading}>
        <div className="wire-grid page-section peak-grid peak-dashboard-grid">
          <section className="wire-card peak-panel peak-runtime-panel">
            <div className="wire-card-title">集群实跑及建议切量水位线展示</div>
            <div className="resource-chart peak-line-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={peakRuntime} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke="rgba(230, 247, 255, .38)" />
                  <XAxis dataKey="time" tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 1000]} tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="clusterA" name="Cluster-A" stroke="#27d7ff" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="clusterB" name="Cluster-B" stroke="#5dffb2" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="clusterC" name="Cluster-C" stroke="#ffb347" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="clusterD" name="Cluster-D" stroke="#ff9fb0" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="watermark" name="建议水位线" stroke="#ffd166" strokeDasharray="2 4" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card peak-panel peak-resource-panel">
            <div className="wire-card-title">削峰后资源情况及收益情况</div>
            <div className="metric-strip peak-metric-strip">
              <div><span>削峰后冗余 TPM</span><strong>{numberText(shavingResources.reduce((sum, item) => sum + item.redundant, 0))}</strong></div>
              <div><span>建议方案数</span><strong>{numberText(shavingResources.length)}</strong></div>
              <div><span>资源收益</span><strong>{money(resourceGain)}</strong></div>
            </div>
            <div className="resource-chart peak-bar-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={shavingResources} margin={{ top: 8, right: 6, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="2 3" vertical={false} stroke="rgba(230, 247, 255, .28)" />
                  <XAxis dataKey="cluster" tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Bar dataKey="redundant" name="削峰后冗余 TPM" fill="#27d7ff" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="gain" name="资源收益" fill="#5dffb2" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <Table size="small" rowKey="cluster" className="peak-compact-table" dataSource={clusterActions} pagination={false} scroll={{ x: 'max-content' }} columns={[{ title: '集群', dataIndex: 'cluster' }, { title: '腾挪资源方案', dataIndex: 'move' }, { title: '划水位线方案', dataIndex: 'watermark' }, { title: '保护层级', dataIndex: 'protected' }]} />
          </section>

          <section className="wire-card peak-panel peak-forecast-panel">
            <div className="wire-card-title">削峰调整方案预估收益</div>
            <div className="circle-metric peak-gain-metric"><strong>{money(displayGain)}</strong><span>定向搬迁新增收入</span></div>
            <Table size="small" rowKey="date" className="peak-compact-table" dataSource={shavingForecast} pagination={false} scroll={{ x: 'max-content' }} columns={[{ title: '日期', dataIndex: 'date' }, { title: '削峰前 TPM', dataIndex: 'before', render: numberText }, { title: '削峰后 TPM', dataIndex: 'after', render: numberText }, { title: '削峰 TPM', dataIndex: 'shaved', render: numberText }, { title: '削峰前机器台数', dataIndex: 'beforeMachines', render: numberText }, { title: '削峰后机器台数', dataIndex: 'afterMachines', render: numberText }]} />
            <Table size="small" rowKey="policyNo" className="peak-compact-table peak-policy-table" dataSource={forecastPolicies} pagination={false} onRow={(record) => ({ onClick: () => { const policy = peakPolicies.find((item) => item.id === record.policyId); if (policy) openDetail(policy); } })} columns={[{ title: '策略编号', dataIndex: 'policyNo' }, { title: '预估收益', dataIndex: 'expectedGain', render: money }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} />
          </section>

          <section className="wire-card peak-panel peak-history-panel">
            <div className="wire-card-title">历史收益累计及实际收益偏差分析</div>
            <div className="resource-chart peak-history-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={revenueTrend} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke="rgba(230, 247, 255, .26)" />
                  <XAxis dataKey="day" tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#7fa5b7', fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="expected" name="预估收益" stroke="#27d7ff" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="actual" name="实际收益" stroke="#5dffb2" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="gap" name="收益偏差" stroke="#ff9fb0" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <Table size="small" rowKey="day" className="peak-compact-table" dataSource={revenueTrend.slice(-4)} pagination={false} columns={[{ title: '日期', dataIndex: 'day' }, { title: '预估', dataIndex: 'expected', render: money }, { title: '实际', dataIndex: 'actual', render: money }, { title: '偏差', dataIndex: 'gap', render: money }]} />
          </section>
        </div>
      </Spin>

      <Modal title="生成削峰策略" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form layout="vertical" onFinish={createRun} initialValues={{ template: 'peak_shaving' }}>
          <Form.Item name="template" label="策略模板"><Select disabled options={[{ label: '削峰策略', value: 'peak_shaving' }]} /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>生成</Button>
        </Form>
      </Modal>
      <Drawer title="削峰策略详情" open={!!selected} onClose={() => { setSelected(null); setDetail(null); }} width={720}>
        {selected && <Space style={{ marginBottom: 16 }}><Button onClick={() => setEditOpen(true)}>修改</Button><Button type="primary" disabled={selected.status !== 'draft'} onClick={() => accept(selected)}>生效</Button><Button danger disabled={selected.status === 'cancelled'} onClick={() => abandon(selected)}>放弃</Button></Space>}
        {detail && <><Descriptions bordered size="small" column={2}><Descriptions.Item label="策略号">{detail.policy.policy_no}</Descriptions.Item><Descriptions.Item label="状态"><StatusTag value={detail.policy.status} /></Descriptions.Item><Descriptions.Item label="算法">{detail.policy.algorithm}</Descriptions.Item><Descriptions.Item label="预估收益">{money(detail.policy.expected_revenue_gain)}</Descriptions.Item><Descriptions.Item label="生效时间">{dateText(detail.policy.effective_from)}</Descriptions.Item><Descriptions.Item label="结束时间">{dateText(detail.policy.effective_to)}</Descriptions.Item></Descriptions><JsonBlock value={{ summary: detail.policy.summary_json, constraints: detail.policy.constraints_json, actions: detail.actions }} /></>}
      </Drawer>
      <Modal title="修改削峰策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
        <Form layout="vertical" onFinish={patch} initialValues={{ summary_json: JSON.stringify(detail?.policy.summary_json || {}, null, 2), constraints_json: JSON.stringify(detail?.policy.constraints_json || {}, null, 2), expected_revenue_gain: String(detail?.policy.expected_revenue_gain || '') }}>
          <Form.Item name="summary_json" label="策略摘要 JSON"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="constraints_json" label="约束 JSON"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="expected_revenue_gain" label="预估收益"><Input /></Form.Item>
          <Form.Item name="effective_from" label="生效时间"><Input placeholder="ISO 时间" /></Form.Item>
          <Form.Item name="effective_to" label="结束时间"><Input placeholder="ISO 时间" /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>保存</Button>
        </Form>
      </Modal>
    </>
  );
}
