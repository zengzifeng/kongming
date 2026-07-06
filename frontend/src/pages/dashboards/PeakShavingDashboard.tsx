import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { EmptyState } from '../../components/EmptyState';
import { policiesApi } from '../../api/kongming';
import type { Policy, PolicyDetail } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';

const peakRuntime = [
  { time: '09:00', actual: 520, p90: 610, p99: 760, movingAvg: 540, suggestedLine: 680 },
  { time: '10:00', actual: 640, p90: 620, p99: 780, movingAvg: 590, suggestedLine: 690 },
  { time: '11:00', actual: 820, p90: 660, p99: 810, movingAvg: 680, suggestedLine: 710 },
  { time: '12:00', actual: 760, p90: 690, p99: 840, movingAvg: 710, suggestedLine: 720 },
  { time: '13:00', actual: 920, p90: 720, p99: 880, movingAvg: 760, suggestedLine: 740 },
  { time: '14:00', actual: 700, p90: 710, p99: 860, movingAvg: 730, suggestedLine: 735 },
  { time: '15:00', actual: 660, p90: 690, p99: 830, movingAvg: 705, suggestedLine: 720 },
];

const shavingResources = [
  { cluster: 'Cluster-A', redundant: 360, gain: 1800, action: '超过水位线部分切至三方', ratio: '18%' },
  { cluster: 'Cluster-B', redundant: 420, gain: 2200, action: '移动平均上沿限流', ratio: '22%' },
  { cluster: 'Cluster-C', redundant: 290, gain: 1300, action: 'P99 保护，P90 以上削峰', ratio: '15%' },
];

const revenueTrend = [
  { day: 'D-6', expected: 1800, actual: 1600, gap: -200 },
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
  const totalGain = peakPolicies.reduce((sum, item) => sum + Number(item.expected_peak_shaving_gain || item.expected_revenue_gain || 0), 0);
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
        <div className="wire-grid page-section peak-grid">
          <section className="wire-card dashboard-panel-wide">
            <div className="wire-card-title">集群实跑及建议切量水位线展示</div>
            <div className="resource-chart tall-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={peakRuntime}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="actual" name="各集群实跑" stroke="#27d7ff" strokeWidth={2} />
                  <Line type="monotone" dataKey="p90" name="P90" stroke="#5dffb2" />
                  <Line type="monotone" dataKey="p99" name="P99" stroke="#ff5f6d" />
                  <Line type="monotone" dataKey="movingAvg" name="移动平均" stroke="#9b8cff" strokeDasharray="5 5" />
                  <Line type="monotone" dataKey="suggestedLine" name="建议切水位线" stroke="#ffb347" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card dashboard-panel-wide">
            <div className="wire-card-title">削峰后资源情况及收益情况</div>
            <div className="metric-strip">
              <div><span>削峰后冗余 TPM</span><strong>{numberText(shavingResources.reduce((sum, item) => sum + item.redundant, 0))}</strong></div>
              <div><span>建议方案数</span><strong>{numberText(shavingResources.length)}</strong></div>
              <div><span>资源收益</span><strong>{money(resourceGain)}</strong></div>
            </div>
            <div className="split-panel">
              <div className="resource-chart short-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={shavingResources}><XAxis dataKey="cluster" /><YAxis /><Tooltip /><Bar dataKey="redundant" name="削峰后冗余" fill="#27d7ff" /><Bar dataKey="gain" name="收益" fill="#5dffb2" /></BarChart></ResponsiveContainer></div>
              <Table size="small" rowKey="cluster" dataSource={shavingResources} pagination={false} columns={[{ title: '集群', dataIndex: 'cluster' }, { title: '建议方案', dataIndex: 'action' }, { title: '切量比例', dataIndex: 'ratio' }, { title: '释放 TPM', dataIndex: 'redundant', render: numberText }, { title: '收益', dataIndex: 'gain', render: money }]} />
            </div>
          </section>

          <section className="wire-card">
            <div className="wire-card-title">削峰调整方案预估收益</div>
            <div className="circle-metric solo-metric"><strong>{money(totalGain || resourceGain)}</strong><span>削峰预估收益</span></div>
            {peakPolicies.length ? <Table<Policy> size="small" rowKey="id" dataSource={peakPolicies} pagination={{ pageSize: 5 }} scroll={{ x: 'max-content' }} onRow={(record) => ({ onClick: () => openDetail(record) })} columns={[{ title: '策略编号', dataIndex: 'policy_no' }, { title: '预估收益', dataIndex: 'expected_revenue_gain', render: money }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} /> : <EmptyState />}
          </section>

          <section className="wire-card">
            <div className="wire-card-title">历史收益累计及实际收益偏差分析</div>
            <div className="resource-chart short-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={revenueTrend}><XAxis dataKey="day" /><YAxis /><Tooltip /><Line type="monotone" dataKey="expected" name="预估收益" stroke="#27d7ff" /><Line type="monotone" dataKey="actual" name="实际收益" stroke="#5dffb2" /><Line type="monotone" dataKey="gap" name="收益偏差" stroke="#ff5f6d" /></LineChart></ResponsiveContainer></div>
            <Table size="small" rowKey="day" dataSource={revenueTrend.slice(-4)} pagination={false} columns={[{ title: '日期', dataIndex: 'day' }, { title: '预估', dataIndex: 'expected', render: money }, { title: '实际', dataIndex: 'actual', render: money }, { title: '偏差', dataIndex: 'gap', render: money }]} />
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
