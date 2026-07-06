import { Button, Descriptions, Form, Input, message, Modal, Space, Spin, Table } from 'antd';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ChartPanel } from '../../components/ChartPanel';
import { ErrorState } from '../../components/ErrorState';
import { policiesApi } from '../../api/kongming';
import type { PolicyAction } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';

export function PolicyDetailPage() {
  const id = Number(useParams().id);
  const [mode, setMode] = useState<'accept' | 'recalculate' | 'cancel' | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { data, error, loading, reload } = useAsync(() => policiesApi.detail(id), [id]);
  const policy = data?.policy;

  async function submit(values: { operator?: string; effective_from?: string; comment?: string; reason?: string; params?: string }) {
    setSubmitting(true);
    try {
      if (mode === 'accept') await policiesApi.accept(id, { operator: values.operator || '', effective_from: values.effective_from, comment: values.comment });
      if (mode === 'recalculate') await policiesApi.recalculate(id, parseJsonObject(values.params));
      if (mode === 'cancel') await policiesApi.cancel(id, { operator: values.operator || '', reason: values.reason || '' });
      message.success('策略操作已提交');
      setMode(null);
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Policy Detail" title={`策略 ${policy?.policy_no || id}`} description="审查策略收益拆分、约束与动作，并执行接受、重算或取消。" actions={<Space><Button disabled={policy?.status !== 'draft'} type="primary" onClick={() => setMode('accept')}>接受</Button><Button onClick={() => setMode('recalculate')}>重算</Button><Button disabled={policy?.status === 'cancelled'} danger onClick={() => setMode('cancel')}>取消</Button></Space>} />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        {policy && <>
          <div className="dashboard-grid two">
            <ChartPanel title="策略信息">
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="状态"><StatusTag value={policy.status} /></Descriptions.Item>
                <Descriptions.Item label="算法">{policy.algorithm}</Descriptions.Item>
                <Descriptions.Item label="收入增益">{money(policy.expected_revenue_gain)}</Descriptions.Item>
                <Descriptions.Item label="削峰收益">{money(policy.expected_peak_shaving_gain)}</Descriptions.Item>
                <Descriptions.Item label="低峰收益">{money(policy.expected_off_peak_gain)}</Descriptions.Item>
                <Descriptions.Item label="生效开始">{dateText(policy.effective_from)}</Descriptions.Item>
                <Descriptions.Item label="接受人">{policy.accepted_by || '-'}</Descriptions.Item>
                <Descriptions.Item label="接受时间">{dateText(policy.accepted_at)}</Descriptions.Item>
                <Descriptions.Item label="取消原因" span={2}>{policy.cancel_reason || '-'}</Descriptions.Item>
              </Descriptions>
            </ChartPanel>
            <ChartPanel title="摘要与约束"><JsonBlock value={{ summary: policy.summary_json, constraints: policy.constraints_json }} /></ChartPanel>
          </div>
          <ChartPanel title="策略动作">
            <Table<PolicyAction> rowKey="id" dataSource={data?.actions || []} pagination={false} columns={[{ title: '动作', dataIndex: 'action_type' }, { title: '预期收益', dataIndex: 'expected_gain', render: money }, { title: '载荷', dataIndex: 'payload_json', render: (v) => <JsonBlock value={v} /> }]} />
          </ChartPanel>
        </>}
      </Spin>
      <Modal title={mode === 'accept' ? '接受策略' : mode === 'cancel' ? '取消策略' : '重算策略'} open={!!mode} footer={null} onCancel={() => setMode(null)}>
        <Form layout="vertical" onFinish={submit}>
          {mode !== 'recalculate' && <Form.Item name="operator" label="操作人" rules={[{ required: true, message: '请输入操作人' }]}><Input /></Form.Item>}
          {mode === 'accept' && <><Form.Item name="effective_from" label="生效时间"><Input placeholder="ISO 时间" /></Form.Item><Form.Item name="comment" label="备注"><Input.TextArea rows={3} /></Form.Item></>}
          {mode === 'recalculate' && <Form.Item name="params" label="参数 JSON"><Input.TextArea rows={4} /></Form.Item>}
          {mode === 'cancel' && <Form.Item name="reason" label="取消原因" rules={[{ required: true, message: '请输入取消原因' }]}><Input.TextArea rows={3} /></Form.Item>}
          <Button loading={submitting} type="primary" htmlType="submit" block>提交</Button>
        </Form>
      </Modal>
    </>
  );
}
