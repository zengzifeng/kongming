import { Button, Form, Input, message, Modal, Select, Spin, Table } from 'antd';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ErrorState } from '../../components/ErrorState';
import { policiesApi } from '../../api/kongming';
import type { PolicyRun } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText } from '../../utils/format';
import { parseJsonObject, parseNumberList } from '../../utils/json';

export function PolicyRunPage() {
  const [query, setQuery] = useState({ page: 1, page_size: 10 });
  const [snapshot, setSnapshot] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const { data, error, loading, reload } = useAsync(() => policiesApi.runs(query), [JSON.stringify(query)]);

  async function create(values: { algorithm: string; demand_ids?: string; params?: string }) {
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: values.algorithm || 'realtime', demand_ids: parseNumberList(values.demand_ids), params: parseJsonObject(values.params) });
      message.success('策略运行已提交');
      await reload();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  }

  async function openSnapshot(id: number) {
    setSnapshot(await policiesApi.snapshot(id));
  }

  return (
    <>
      <PageHeader eyebrow="Policy Runs" title="策略运行" description="手动提交实时或时段策略计算，查看运行状态与输入快照。" />
      <Form layout="inline" className="filter-bar" onFinish={create} initialValues={{ algorithm: 'realtime' }}>
        <Form.Item name="algorithm" label="算法"><Select style={{ width: 150 }} options={['realtime','time_period'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="demand_ids" label="需求 IDs"><Input placeholder="1,2,3" /></Form.Item>
        <Form.Item name="params" label="参数 JSON"><Input placeholder={'{"key":"value"}'} /></Form.Item>
        <Button loading={submitting} type="primary" htmlType="submit">创建运行</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <Table<PolicyRun>
          rowKey="id"
          dataSource={data?.items || []}
          pagination={{ current: data?.page || 1, pageSize: data?.page_size || 10, total: data?.total || 0, onChange: (page, pageSize) => setQuery({ ...query, page, page_size: pageSize }) }}
          columns={[
            { title: '运行号', dataIndex: 'run_no' },
            { title: '算法', dataIndex: 'algorithm' },
            { title: '触发', dataIndex: 'triggered_by' },
            { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> },
            { title: '开始', dataIndex: 'started_at', render: dateText },
            { title: '结束', dataIndex: 'finished_at', render: dateText },
            { title: '耗时 ms', dataIndex: 'duration_ms' },
            { title: '操作', render: (_, r) => <Button onClick={() => openSnapshot(r.id)}>输入快照</Button> },
          ]}
        />
      </Spin>
      <Modal title="输入快照" open={snapshot !== null} footer={null} onCancel={() => setSnapshot(null)} width={760}><JsonBlock value={snapshot} /></Modal>
    </>
  );
}
