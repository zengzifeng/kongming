import { Button, Form, Input, message, Modal, Spin, Table } from 'antd';
import { Pie, PieChart, ResponsiveContainer, Cell, Tooltip } from 'recharts';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { ErrorState } from '../../components/ErrorState';
import { revenueApi } from '../../api/kongming';
import type { RevenueAnalysisItem } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { money, percent } from '../../utils/format';

export function RevenueAttributionPage() {
  const [archiveTarget, setArchiveTarget] = useState<RevenueAnalysisItem | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { data, error, loading, reload } = useAsync(() => revenueApi.analysis(), []);
  const overviewPie = data ? [
    { name: '达成', value: data.overview.achieved },
    { name: '未达成', value: data.overview.not_achieved },
  ] : [];
  const algorithmPie = data ? Object.entries(data.overview.by_algorithm).map(([name, value]) => ({ name, value: value.total })) : [];

  async function archive(values: { operator: string; reason: string }) {
    if (!archiveTarget) return;
    setSubmitting(true);
    try {
      await revenueApi.archiveAnalysis(archiveTarget.policy_id, values);
      message.success('已归档');
      setArchiveTarget(null);
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  const columns = [
    { title: '策略 ID', dataIndex: 'policy_id' },
    { title: '策略编号', dataIndex: 'policy_no' },
    { title: '算法', dataIndex: 'algorithm' },
    { title: '状态', dataIndex: 'policy_status', render: (v: string) => <StatusTag value={v} /> },
    { title: '达成', dataIndex: 'achievement_status', render: (v: string) => <StatusTag value={v} /> },
    { title: '预期收益', dataIndex: 'expected_revenue_gain', render: money },
    { title: '实际收益', dataIndex: 'actual_revenue_gain', render: money },
    { title: '差额', dataIndex: 'revenue_gap', render: money },
    { title: '分析原因', dataIndex: 'analysis_reason' },
    { title: '归档', dataIndex: 'archived', render: (v: boolean) => v ? '已归档' : '未归档' },
  ];

  return (
    <>
      <PageHeader eyebrow="Revenue Analysis" title="收益归因分析" description="识别未达预期策略，查看效果总览并完成人工归档。" />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <div className="wire-grid revenue-analysis-board">
            <section className="wire-card">
              <div className="wire-card-title">收益不达预期策略详情（未归档）</div>
              <Table<RevenueAnalysisItem> rowKey="policy_id" size="small" dataSource={data?.underperforming || []} pagination={{ pageSize: 5 }} scroll={{ x: 'max-content' }} columns={[...columns, { title: '操作', render: (_: unknown, record: RevenueAnalysisItem) => <Button onClick={() => setArchiveTarget(record)}>归档</Button> }]} />
            </section>
            <section className="wire-card">
              <div className="wire-card-title">效果总览</div>
              <div className="circle-row analysis-circle-row">
                <div className="circle-metric"><strong>{percent(data?.overview.achieved_ratio)}</strong><span>达成占比</span></div>
                <ResponsiveContainer className="analysis-pie" width="100%" height={220}><PieChart><Pie data={overviewPie} dataKey="value" nameKey="name" innerRadius={44} outerRadius={76} stroke="rgba(7, 16, 24, 0.92)" strokeWidth={2}>{overviewPie.map((_, i) => <Cell key={i} fill={i === 0 ? '#59d8c7' : '#d96b76'} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
                <ResponsiveContainer className="analysis-pie" width="100%" height={220}><PieChart><Pie data={algorithmPie} dataKey="value" nameKey="name" innerRadius={44} outerRadius={76} stroke="rgba(7, 16, 24, 0.92)" strokeWidth={2}>{algorithmPie.map((_, i) => <Cell key={i} fill={['#4bb8d8', '#d8a24b', '#8178d8'][i % 3]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
              </div>
            </section>
            <section className="wire-card wide-card">
              <div className="wire-card-title">所有策略收益分析</div>
              <Table<RevenueAnalysisItem> rowKey="policy_id" size="small" dataSource={data?.items || []} pagination={{ pageSize: 8 }} scroll={{ x: 'max-content' }} columns={columns} />
            </section>
          </div>
      </Spin>
      <Modal title="人工归档" open={!!archiveTarget} footer={null} onCancel={() => setArchiveTarget(null)}>
        <Form layout="vertical" onFinish={archive}>
          <Form.Item name="operator" label="操作人" rules={[{ required: true, message: '请输入操作人' }]}><Input /></Form.Item>
          <Form.Item name="reason" label="分析/归档原因" rules={[{ required: true, message: '请输入原因' }]}><Input.TextArea rows={4} /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>确认归档</Button>
        </Form>
      </Modal>
    </>
  );
}
