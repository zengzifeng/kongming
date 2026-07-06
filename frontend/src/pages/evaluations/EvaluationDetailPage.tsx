import { Button, Descriptions, Form, Input, message, Modal, Space, Spin } from 'antd';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ChartPanel } from '../../components/ChartPanel';
import { ErrorState } from '../../components/ErrorState';
import { evaluationsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, percent } from '../../utils/format';

export function EvaluationDetailPage() {
  const id = Number(useParams().id);
  const [mode, setMode] = useState<'approve' | 'reject' | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { data, error, loading, reload } = useAsync(() => evaluationsApi.detail(id), [id]);
  const decided = data?.status === 'approved' || data?.status === 'rejected';

  async function submit(values: { operator: string; comment?: string; reason?: string }) {
    setSubmitting(true);
    try {
      if (mode === 'approve') await evaluationsApi.approve(id, { operator: values.operator, comment: values.comment });
      if (mode === 'reject') await evaluationsApi.reject(id, { operator: values.operator, reason: values.reason || '' });
      message.success('审批操作已完成');
      setMode(null);
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Evaluation Detail" title={`评估 #${id}`} description="审批评估结论，记录审批人、意见或驳回原因。" actions={<Space><Button disabled={decided} type="primary" onClick={() => setMode('approve')}>通过</Button><Button disabled={decided} danger onClick={() => setMode('reject')}>驳回</Button></Space>} />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        {data && <div className="dashboard-grid two">
          <ChartPanel title="评估结果">
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="状态"><StatusTag value={data.status} /></Descriptions.Item>
              <Descriptions.Item label="推荐"><StatusTag value={data.recommendation} /></Descriptions.Item>
              <Descriptions.Item label="需求 ID">{data.demand_id}</Descriptions.Item>
              <Descriptions.Item label="可行性">{percent(data.feasibility_score)}</Descriptions.Item>
              <Descriptions.Item label="客户价值">{percent(data.customer_value_score)}</Descriptions.Item>
              <Descriptions.Item label="预计收入">{money(data.expected_revenue)}</Descriptions.Item>
              <Descriptions.Item label="预计成本">{money(data.expected_cost)}</Descriptions.Item>
              <Descriptions.Item label="预计毛利">{money(data.expected_margin)}</Descriptions.Item>
              <Descriptions.Item label="决策人">{data.decided_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="决策时间">{dateText(data.decided_at)}</Descriptions.Item>
              <Descriptions.Item label="原因" span={2}>{data.decided_reason || '-'}</Descriptions.Item>
            </Descriptions>
          </ChartPanel>
          <ChartPanel title="评估因素"><JsonBlock value={data.factors_json} /></ChartPanel>
        </div>}
      </Spin>
      <Modal title={mode === 'approve' ? '通过评估' : '驳回评估'} open={!!mode} footer={null} onCancel={() => setMode(null)}>
        <Form layout="vertical" onFinish={submit}>
          <Form.Item name="operator" label="操作人" rules={[{ required: true, message: '请输入操作人' }]}><Input /></Form.Item>
          {mode === 'approve' && <Form.Item name="comment" label="审批意见"><Input.TextArea rows={3} /></Form.Item>}
          {mode === 'reject' && <Form.Item name="reason" label="驳回原因" rules={[{ required: true, message: '请输入驳回原因' }]}><Input.TextArea rows={3} /></Form.Item>}
          <Button loading={submitting} type="primary" htmlType="submit" block>{mode === 'approve' ? '确认通过' : '确认驳回'}</Button>
        </Form>
      </Modal>
    </>
  );
}
