import { Button, Descriptions, Drawer, Form, Input, message, Modal, Select, Space, Spin, Switch } from 'antd';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ChartPanel } from '../../components/ChartPanel';
import { ErrorState } from '../../components/ErrorState';
import { demandsApi, evaluationsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { dateText, numberText, percent } from '../../utils/format';

const transitions: Record<string, string[]> = {
  pending: ['evaluating', 'rejected', 'closed'],
  evaluating: ['awaiting_approval', 'approved', 'rejected'],
  awaiting_approval: ['approved', 'rejected'],
  approved: ['scheduled', 'rejected', 'closed'],
  scheduled: ['live', 'closed'],
  live: ['closed'],
  closed: [],
  rejected: [],
};

export function DemandDetailPage() {
  const id = Number(useParams().id);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [auditMode, setAuditMode] = useState<'approve' | 'reject' | null>(null);
  const [force, setForce] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { data, error, loading, reload } = useAsync(() => demandsApi.detail(id), [id]);
  const demand = data?.demand;
  const latest = data?.latest_evaluation;
  const canAudit = latest?.status === 'pending';

  async function evaluate() {
    setSubmitting(true);
    try {
      await demandsApi.evaluate(id, force);
      message.success('评估已发起');
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  async function patch(values: Record<string, unknown>) {
    setSubmitting(true);
    try {
      await demandsApi.patch(id, values);
      message.success('需求已更新');
      setDrawerOpen(false);
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  async function audit(values: { operator: string; comment?: string; reason?: string }) {
    if (!latest) return;
    setSubmitting(true);
    try {
      if (auditMode === 'approve') await evaluationsApi.approve(latest.id, { operator: values.operator, comment: values.comment });
      if (auditMode === 'reject') await evaluationsApi.reject(latest.id, { operator: values.operator, reason: values.reason || '' });
      message.success('审核已完成');
      setAuditMode(null);
      await reload();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Demand Detail"
        title={`需求 ${demand?.report_id || id}`}
        description="查看需求基础字段、最新评估结果，并执行状态维护、评估触发和审核动作。"
        actions={<Space><Switch checked={force} onChange={setForce} checkedChildren="强制" unCheckedChildren="普通" /><Button loading={submitting} onClick={evaluate} type="primary">发起评估</Button>{canAudit && <><Button onClick={() => setAuditMode('approve')}>通过评估</Button><Button danger onClick={() => setAuditMode('reject')}>驳回评估</Button></>}<Button onClick={() => setDrawerOpen(true)}>编辑需求</Button></Space>}
      />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        {demand && <div className="dashboard-grid two">
          <ChartPanel title="需求信息">
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="状态"><StatusTag value={demand.status} /></Descriptions.Item>
              <Descriptions.Item label="客户 ID">{demand.customer_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="模型">{demand.model_name}</Descriptions.Item>
              <Descriptions.Item label="TPM">{numberText(demand.expected_tpm)}</Descriptions.Item>
              <Descriptions.Item label="RPM">{numberText(demand.expected_rpm)}</Descriptions.Item>
              <Descriptions.Item label="折扣">{percent(demand.discount_rate)}</Descriptions.Item>
              <Descriptions.Item label="开始">{dateText(demand.expected_start_at)}</Descriptions.Item>
              <Descriptions.Item label="结束">{dateText(demand.expected_end_at)}</Descriptions.Item>
              <Descriptions.Item label="完整度">{percent(demand.field_completeness_score)}</Descriptions.Item>
              <Descriptions.Item label="来源批次">{demand.source_batch_id || '-'}</Descriptions.Item>
            </Descriptions>
          </ChartPanel>
          <ChartPanel title="最新评估"><JsonBlock value={latest || { message: '暂无评估' }} /></ChartPanel>
        </div>}
      </Spin>
      <Drawer title="编辑需求" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={460}>
        <Form layout="vertical" onFinish={patch} initialValues={{ status: demand?.status, expected_start_at: demand?.expected_start_at || undefined, expected_end_at: demand?.expected_end_at || undefined }}>
          <Form.Item name="status" label="状态"><Select options={(transitions[demand?.status || ''] || []).map((v) => ({ label: v, value: v }))} placeholder="选择合法下一状态" /></Form.Item>
          <Form.Item name="expected_start_at" label="期望开始时间"><Input placeholder="ISO 时间，如 2026-06-28T10:00:00" /></Form.Item>
          <Form.Item name="expected_end_at" label="期望结束时间"><Input placeholder="ISO 时间" /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>提交</Button>
        </Form>
      </Drawer>
      <Modal title={auditMode === 'approve' ? '通过评估' : '驳回评估'} open={!!auditMode} footer={null} onCancel={() => setAuditMode(null)}>
        <Form layout="vertical" onFinish={audit}>
          <Form.Item name="operator" label="操作人" rules={[{ required: true, message: '请输入操作人' }]}><Input /></Form.Item>
          {auditMode === 'approve' && <Form.Item name="comment" label="意见"><Input.TextArea rows={3} /></Form.Item>}
          {auditMode === 'reject' && <Form.Item name="reason" label="驳回原因" rules={[{ required: true, message: '请输入驳回原因' }]}><Input.TextArea rows={3} /></Form.Item>}
          <Button loading={submitting} type="primary" htmlType="submit" block>提交</Button>
        </Form>
      </Modal>
    </>
  );
}
