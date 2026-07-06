import { Button, Dropdown, Form, Input, InputNumber, Select, Space, Spin, Table, message } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { ErrorState } from '../../components/ErrorState';
import { demandsApi } from '../../api/kongming';
import type { Demand } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, numberText, percent } from '../../utils/format';

const statuses = ['pending','evaluating','awaiting_approval','approved','scheduled','live','closed','rejected'];
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

export function DemandListPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [query, setQuery] = useState({ page: 1, page_size: 10, status: params.get('status') || undefined });
  const { data, error, loading, reload } = useAsync(() => demandsApi.list(query), [JSON.stringify(query)]);
  const initialValues = useMemo(() => ({ status: query.status }), [query.status]);

  async function evaluate(record: Demand) {
    await demandsApi.evaluate(record.id, false);
    message.success('评估已发起');
    await reload();
  }

  async function flow(record: Demand, status: string) {
    await demandsApi.patch(record.id, { status });
    message.success(`需求已流转到 ${status}`);
    await reload();
  }

  return (
    <>
      <PageHeader eyebrow="Demands" title="需求看板" description="承接报备需求，支持评估触发、状态流转和审核闭环。" />
      <Form layout="inline" className="filter-bar" initialValues={initialValues} onFinish={(values) => setQuery({ ...query, ...values, page: 1 })}>
        <Form.Item name="status" label="状态"><Select allowClear style={{ width: 180 }} options={statuses.map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="customer_id" label="客户 ID"><InputNumber min={1} /></Form.Item>
        <Form.Item name="model" label="模型"><Input allowClear /></Form.Item>
        <Button type="primary" htmlType="submit">筛选</Button>
        <Button onClick={() => setQuery({ page: 1, page_size: 10, status: undefined })}>重置</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <Table<Demand>
          rowKey="id"
          dataSource={data?.items || []}
          pagination={{ current: data?.page || 1, pageSize: data?.page_size || 10, total: data?.total || 0, onChange: (page, pageSize) => setQuery({ ...query, page, page_size: pageSize }) }}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '报备 ID', dataIndex: 'report_id' },
            { title: '客户', dataIndex: 'customer_id' },
            { title: '模型', dataIndex: 'model_name' },
            { title: 'TPM', dataIndex: 'expected_tpm', render: numberText },
            { title: 'RPM', dataIndex: 'expected_rpm', render: numberText },
            { title: '折扣', dataIndex: 'discount_rate', render: percent },
            { title: '完整度', dataIndex: 'field_completeness_score', render: percent },
            { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> },
            { title: '开始时间', dataIndex: 'expected_start_at', render: dateText },
            {
              title: '操作',
              fixed: 'right',
              render: (_, record) => {
                const next = transitions[record.status] || [];
                return <Space onClick={(e) => e.stopPropagation()}><Button onClick={() => navigate(`/demands/${record.id}`)}>查看</Button><Button onClick={() => evaluate(record)}>发起评估</Button>{next.length > 0 && <Dropdown menu={{ items: next.map((status) => ({ key: status, label: status })), onClick: ({ key }) => flow(record, key) }}><Button>状态流转</Button></Dropdown>}</Space>;
              },
            },
          ]}
        />
      </Spin>
    </>
  );
}
