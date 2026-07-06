import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { Pie, PieChart, ResponsiveContainer, Cell, Tooltip, LineChart, Line, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { policiesApi } from '../../api/kongming';
import type { Policy, PolicyDetail } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { money, dateText } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';

const templateMap: Record<string, string> = {
  realtime: '实时策略',
  off_peak: '闲忙时策略',
  peak_shaving: '削峰策略',
};

const trendMock = [
  { time: 'D-4', gain: 1200 },
  { time: 'D-3', gain: 2400 },
  { time: 'D-2', gain: 1900 },
  { time: 'D-1', gain: 3200 },
  { time: '今日', gain: 4100 },
];

function pickPolicy(policies: Policy[], key: string) {
  return policies.find((item) => item.algorithm === key || JSON.stringify(item.summary_json || {}).includes(key)) || null;
}

export function StrategyDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Policy | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const items = policies.data?.items || [];

  const expectedPie = useMemo(() => items.slice(0, 6).map((item) => ({ name: item.policy_no, value: Number(item.expected_revenue_gain || 0) })), [items]);
  const totalGain = expectedPie.reduce((sum, item) => sum + item.value, 0);

  async function createRun(values: { template: string }) {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: values.template, params: { template: templateMap[values.template] } });
      message.success('策略生成已提交');
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

  const realtime = pickPolicy(items, 'realtime');
  const offPeak = pickPolicy(items, 'off_peak');
  const peak = pickPolicy(items, 'peak_shaving');
  const strategyCards: Array<{ title: string; policy: Policy | null }> = [
    { title: '闲忙时策略', policy: offPeak },
    { title: '削峰策略', policy: peak },
    { title: '实时策略', policy: realtime },
  ];

  return (
    <>
      <PageHeader eyebrow="Strategies" title="策略看板" description="生成策略、查看单策略详情、执行修改、生效或放弃，并追踪整体收益。" actions={<Button type="primary" onClick={() => setCreateOpen(true)}>策略生成</Button>} />
      <Spin spinning={policies.loading}>
        <div className="wire-grid">
            <section className="wire-card">
              <div className="wire-card-title">今日策略</div>
              <div className="strategy-mini-grid">
                {strategyCards.map(({ title, policy }) => <button className="strategy-mini-card" key={title} onClick={() => policy && openDetail(policy)}><strong>{title}</strong>{policy ? <><span>{policy.policy_no}</span><small>{money(policy.expected_revenue_gain)}</small><StatusTag value={policy.status} /></> : <small>暂无策略</small>}</button>)}
              </div>
            </section>
            <section className="wire-card">
              <div className="wire-card-title">今日收益汇总</div>
              <div className="circle-row">
                <div className="circle-metric"><strong>{money(totalGain)}</strong><span>预计收益</span></div>
                <ResponsiveContainer width="55%" height={220}><PieChart><Pie data={expectedPie} dataKey="value" nameKey="name" innerRadius={46} outerRadius={86}>{expectedPie.map((_, i) => <Cell key={i} fill={['#27d7ff','#5dffb2','#ffb347','#9b8cff','#ff5f6d'][i % 5]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
              </div>
            </section>
            <section className="wire-card">
              <div className="wire-card-title">历史调整策略信息查询</div>
              <Table<Policy> size="small" rowKey="id" dataSource={items} pagination={{ pageSize: 6 }} scroll={{ x: 'max-content' }} onRow={(record) => ({ onClick: () => openDetail(record) })} columns={[{ title: '策略 ID', dataIndex: 'id' }, { title: '策略名称/编号', dataIndex: 'policy_no' }, { title: '算法', dataIndex: 'algorithm' }, { title: '预估收益', dataIndex: 'expected_revenue_gain', render: money }, { title: '生效时间', dataIndex: 'effective_from', render: dateText }, { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> }]} />
            </section>
            <section className="wire-card">
              <div className="wire-card-title">整体收益汇总</div>
              <div className="split-panel"><div className="stable-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={trendMock}><XAxis dataKey="time" /><YAxis /><Tooltip /><Line type="monotone" dataKey="gain" stroke="#27d7ff" /></LineChart></ResponsiveContainer></div><Table<Policy> size="small" rowKey="id" dataSource={items.slice(0, 5)} pagination={false} scroll={{ x: 'max-content' }} columns={[{ title: '策略', dataIndex: 'policy_no' }, { title: '收益', dataIndex: 'expected_revenue_gain', render: money }]} /></div>
            </section>
          </div>
      </Spin>
      <Modal title="策略生成" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form layout="vertical" onFinish={createRun} initialValues={{ template: 'realtime' }}>
          <Form.Item name="template" label="策略模板" rules={[{ required: true }]}><Select options={[{ label: '实时策略', value: 'realtime' }, { label: '闲忙时策略', value: 'off_peak' }, { label: '削峰策略', value: 'peak_shaving' }]} /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>生成</Button>
        </Form>
      </Modal>
      <Drawer title="策略详情" open={!!selected} onClose={() => { setSelected(null); setDetail(null); }} width={720}>
        {selected && <Space style={{ marginBottom: 16 }}><Button onClick={() => setEditOpen(true)}>修改</Button><Button type="primary" disabled={selected.status !== 'draft'} onClick={() => accept(selected)}>生效</Button><Button danger disabled={selected.status === 'cancelled'} onClick={() => abandon(selected)}>放弃</Button></Space>}
        {detail && <><Descriptions bordered size="small" column={2}><Descriptions.Item label="策略号">{detail.policy.policy_no}</Descriptions.Item><Descriptions.Item label="状态"><StatusTag value={detail.policy.status} /></Descriptions.Item><Descriptions.Item label="算法">{detail.policy.algorithm}</Descriptions.Item><Descriptions.Item label="预估收益">{money(detail.policy.expected_revenue_gain)}</Descriptions.Item><Descriptions.Item label="生效时间">{dateText(detail.policy.effective_from)}</Descriptions.Item><Descriptions.Item label="结束时间">{dateText(detail.policy.effective_to)}</Descriptions.Item></Descriptions><JsonBlock value={{ summary: detail.policy.summary_json, constraints: detail.policy.constraints_json, actions: detail.actions }} /></>}
      </Drawer>
      <Modal title="修改策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
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
