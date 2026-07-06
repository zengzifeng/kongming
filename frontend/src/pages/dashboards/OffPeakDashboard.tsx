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

const fittingMock = [
  { time: '00:00', night: 210, nightFit: 230, day: 0, dayFit: 0, redundant: 520 },
  { time: '03:00', night: 180, nightFit: 205, day: 0, dayFit: 0, redundant: 610 },
  { time: '06:00', night: 260, nightFit: 250, day: 0, dayFit: 0, redundant: 480 },
  { time: '09:00', night: 0, nightFit: 0, day: 620, dayFit: 600, redundant: 260 },
  { time: '12:00', night: 0, nightFit: 0, day: 780, dayFit: 740, redundant: 170 },
  { time: '15:00', night: 0, nightFit: 0, day: 700, dayFit: 720, redundant: 210 },
  { time: '18:00', night: 0, nightFit: 0, day: 540, dayFit: 560, redundant: 330 },
];

const revenueTrend = [
  { day: 'D-6', expected: 1100, actual: 980, gap: -120 },
  { day: 'D-5', expected: 1600, actual: 1520, gap: -80 },
  { day: 'D-4', expected: 2100, actual: 2250, gap: 150 },
  { day: 'D-3', expected: 2500, actual: 2360, gap: -140 },
  { day: 'D-2', expected: 3100, actual: 2980, gap: -120 },
  { day: 'D-1', expected: 3600, actual: 3720, gap: 120 },
  { day: '今日', expected: 4200, actual: 4050, gap: -150 },
];

const clusterPlans = [
  { cluster: 'Cluster-A', customer: '客户 1024', move: '夜间批量任务迁入', watermark: '65%', redundant: 610 },
  { cluster: 'Cluster-B', customer: '客户 2048', move: '白天推理限流后腾挪', watermark: '72%', redundant: 480 },
  { cluster: 'Cluster-C', customer: '客户 3072', move: '闲时补偿三方溢出量', watermark: '68%', redundant: 520 },
];

function pickPolicies(policies: Policy[], key: string) {
  return policies.filter((item) => item.algorithm === key || JSON.stringify(item.summary_json || {}).includes(key));
}

export function OffPeakDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Policy | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const offPeakPolicies = useMemo(() => pickPolicies(policies.data?.items || [], 'off_peak'), [policies.data?.items]);
  const totalGain = offPeakPolicies.reduce((sum, item) => sum + Number(item.expected_off_peak_gain || item.expected_revenue_gain || 0), 0);

  async function createRun() {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: 'off_peak', params: { template: '闲忙时策略' } });
      message.success('闲忙时策略生成已提交');
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
      <PageHeader eyebrow="Off Peak" title="闲忙时看板" description="根据前一天或固定时长拟合夜间、白天跑量，评估叠加新增需求后的资源冗余与收益。" actions={<Button type="primary" onClick={() => setCreateOpen(true)}>生成闲忙时策略</Button>} />
      <Spin spinning={policies.loading}>
        <div className="wire-grid page-section">
          <section className="wire-card dashboard-panel-wide">
            <div className="wire-card-title">集群维度夜间跑量/白天跑量拟合</div>
            <div className="resource-chart tall-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={fittingMock}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="night" name="夜间跑量" stroke="#27d7ff" />
                  <Line type="monotone" dataKey="nightFit" name="夜间拟合" stroke="#5dffb2" strokeDasharray="5 5" />
                  <Line type="monotone" dataKey="day" name="白天跑量" stroke="#ffb347" />
                  <Line type="monotone" dataKey="dayFit" name="白天拟合" stroke="#9b8cff" strokeDasharray="5 5" />
                  <Line type="monotone" dataKey="redundant" name="集群冗余" stroke="#ff5f6d" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="wire-card dashboard-panel-wide">
            <div className="wire-card-title">集群调整方案建议</div>
            <Table size="small" rowKey="cluster" dataSource={clusterPlans} pagination={false} columns={[
              { title: '集群', dataIndex: 'cluster' },
              { title: '承接客户', dataIndex: 'customer' },
              { title: '腾挪资源方案', dataIndex: 'move' },
              { title: '划水位线方案', dataIndex: 'watermark' },
              { title: '冗余 TPM', dataIndex: 'redundant', render: numberText },
            ]} />
            {offPeakPolicies.length ? <Table<Policy> className="inner-table" size="small" rowKey="id" dataSource={offPeakPolicies} pagination={{ pageSize: 4 }} scroll={{ x: 'max-content' }} onRow={(record) => ({ onClick: () => openDetail(record) })} columns={[{ title: '策略编号', dataIndex: 'policy_no' }, { title: '算法', dataIndex: 'algorithm' }, { title: '预估收益', dataIndex: 'expected_revenue_gain', render: money }, { title: '生效时间', dataIndex: 'effective_from', render: dateText }, { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> }]} /> : <EmptyState />}
          </section>

          <section className="wire-card">
            <div className="wire-card-title">闲时调整方案预估收益</div>
            <div className="circle-metric solo-metric"><strong>{money(totalGain)}</strong><span>闲时预估收益</span></div>
            <div className="resource-chart short-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={offPeakPolicies.map((item) => ({ name: item.policy_no, gain: item.expected_off_peak_gain || item.expected_revenue_gain }))}><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="gain" name="预估收益" fill="#5dffb2" /></BarChart></ResponsiveContainer></div>
          </section>

          <section className="wire-card">
            <div className="wire-card-title">历史收益累计及实际收益偏差分析</div>
            <div className="resource-chart short-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={revenueTrend}><XAxis dataKey="day" /><YAxis /><Tooltip /><Line type="monotone" dataKey="expected" name="预估收益" stroke="#27d7ff" /><Line type="monotone" dataKey="actual" name="实际收益" stroke="#5dffb2" /><Line type="monotone" dataKey="gap" name="收益偏差" stroke="#ff5f6d" /></LineChart></ResponsiveContainer></div>
            <Table size="small" rowKey="day" dataSource={revenueTrend.slice(-4)} pagination={false} columns={[{ title: '日期', dataIndex: 'day' }, { title: '预估', dataIndex: 'expected', render: money }, { title: '实际', dataIndex: 'actual', render: money }, { title: '偏差', dataIndex: 'gap', render: money }]} />
          </section>
        </div>
      </Spin>

      <Modal title="生成闲忙时策略" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form layout="vertical" onFinish={createRun} initialValues={{ template: 'off_peak' }}>
          <Form.Item name="template" label="策略模板"><Select disabled options={[{ label: '闲忙时策略', value: 'off_peak' }]} /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>生成</Button>
        </Form>
      </Modal>
      <Drawer title="闲忙时策略详情" open={!!selected} onClose={() => { setSelected(null); setDetail(null); }} width={720}>
        {selected && <Space style={{ marginBottom: 16 }}><Button onClick={() => setEditOpen(true)}>修改</Button><Button type="primary" disabled={selected.status !== 'draft'} onClick={() => accept(selected)}>生效</Button><Button danger disabled={selected.status === 'cancelled'} onClick={() => abandon(selected)}>放弃</Button></Space>}
        {detail && <><Descriptions bordered size="small" column={2}><Descriptions.Item label="策略号">{detail.policy.policy_no}</Descriptions.Item><Descriptions.Item label="状态"><StatusTag value={detail.policy.status} /></Descriptions.Item><Descriptions.Item label="算法">{detail.policy.algorithm}</Descriptions.Item><Descriptions.Item label="预估收益">{money(detail.policy.expected_revenue_gain)}</Descriptions.Item><Descriptions.Item label="生效时间">{dateText(detail.policy.effective_from)}</Descriptions.Item><Descriptions.Item label="结束时间">{dateText(detail.policy.effective_to)}</Descriptions.Item></Descriptions><JsonBlock value={{ summary: detail.policy.summary_json, constraints: detail.policy.constraints_json, actions: detail.actions }} /></>}
      </Drawer>
      <Modal title="修改闲忙时策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
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
