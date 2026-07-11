import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { policiesApi } from '../../api/kongming';
import type { Policy, PolicyDetail } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';

const peakRuntime = [
  { time: '09:00', clusterA: 520, clusterB: 620, clusterC: 680, clusterD: 750, watermark: 760 },
  { time: '10:00', clusterA: 610, clusterB: 690, clusterC: 650, clusterD: 780, watermark: 760 },
  { time: '11:00', clusterA: 820, clusterB: 710, clusterC: 690, clusterD: 800, watermark: 760 },
  { time: '12:00', clusterA: 760, clusterB: 710, clusterC: 700, clusterD: 850, watermark: 760 },
  { time: '13:00', clusterA: 920, clusterB: 740, clusterC: 720, clusterD: 900, watermark: 760 },
  { time: '14:00', clusterA: 700, clusterB: 720, clusterC: 690, clusterD: 870, watermark: 760 },
  { time: '15:00', clusterA: 660, clusterB: 700, clusterC: 680, clusterD: 840, watermark: 760 },
];

const shavingResources = [
  { cluster: 'Cluster-A', redundant: 360, gain: 1800 },
  { cluster: 'Cluster-B', redundant: 420, gain: 2200 },
  { cluster: 'Cluster-C', redundant: 290, gain: 1300 },
];

const clusterActions = [
  { cluster: 'Cluster-A', move: '水位线以上切三方', watermark: '760 TPM', protected: 'P0/P1' },
  { cluster: 'Cluster-B', move: '峰值时段柔性限流', watermark: '760 TPM', protected: 'P0/P1' },
  { cluster: 'Cluster-C', move: '低毛利流量后移', watermark: '720 TPM', protected: 'P1' },
  { cluster: 'Cluster-D', move: '保留 P99 容量', watermark: '840 TPM', protected: 'P0' },
];

const shavingForecast = [
  { date: '2026/6/1', before: 5500, after: 4000, shaved: 1500, beforeMachines: 33, afterMachines: 30 },
  { date: '2026/6/2', before: 5350, after: 4000, shaved: 1350, beforeMachines: 33, afterMachines: 29 },
  { date: '2026/6/3', before: 5740, after: 4000, shaved: 1740, beforeMachines: 33, afterMachines: 28 },
];

const forecastPolicies = [
  { policyNo: 'POL-PEAK-0627C', expectedGain: 98000, status: 'accepted' },
];

const revenueTrend = [
  { day: 'D-6', expected: 1700, actual: 1600, gap: -100 },
  { day: 'D-5', expected: 2300, actual: 2380, gap: 80 },
  { day: 'D-4', expected: 2600, actual: 2500, gap: -100 },
  { day: 'D-3', expected: 3100, actual: 3320, gap: 220 },
  { day: 'D-2', expected: 3900, actual: 3610, gap: -290 },
  { day: 'D-1', expected: 4300, actual: 4480, gap: 180 },
  { day: '今日', expected: 5100, actual: 4920, gap: -180 },
];

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
  const peakPolicies = useMemo(() => pickPolicies(policies.data?.items || [], 'peak_shaving'), [policies.data?.items]);
  const displayGain = 98661.89;
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
      <Spin spinning={policies.loading}>
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
            <Table size="small" rowKey="policyNo" className="peak-compact-table peak-policy-table" dataSource={forecastPolicies} pagination={false} onRow={() => ({ onClick: () => peakPolicies[0] && openDetail(peakPolicies[0]) })} columns={[{ title: '策略编号', dataIndex: 'policyNo' }, { title: '预估收益', dataIndex: 'expectedGain', render: money }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} />
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
