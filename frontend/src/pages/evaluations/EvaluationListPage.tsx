import { Button, Form, Select, Spin, Table } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { ErrorState } from '../../components/ErrorState';
import { evaluationsApi } from '../../api/kongming';
import type { Evaluation } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { money, percent } from '../../utils/format';

export function EvaluationListPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState({ page: 1, page_size: 10 });
  const { data, error, loading, reload } = useAsync(() => evaluationsApi.list(query), [JSON.stringify(query)]);
  return (
    <>
      <PageHeader eyebrow="Evaluations" title="评估审批" description="查看可行性、客户价值、收益成本和系统推荐结论。" />
      <Form layout="inline" className="filter-bar" onFinish={(values) => setQuery({ ...query, ...values, page: 1 })}>
        <Form.Item name="status" label="状态"><Select allowClear style={{ width: 160 }} options={['draft','pending','approved','rejected'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="recommendation" label="推荐"><Select allowClear style={{ width: 180 }} options={['auto_approve','manual_review','reject'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Button type="primary" htmlType="submit">筛选</Button>
        <Button onClick={() => setQuery({ page: 1, page_size: 10 })}>重置</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <Table<Evaluation>
          rowKey="id"
          dataSource={data?.items || []}
          onRow={(record) => ({ onClick: () => navigate(`/evaluations/${record.id}`) })}
          pagination={{ current: data?.page || 1, pageSize: data?.page_size || 10, total: data?.total || 0, onChange: (page, pageSize) => setQuery({ ...query, page, page_size: pageSize }) }}
          columns={[
            { title: '需求 ID', dataIndex: 'demand_id' },
            { title: '可行性', dataIndex: 'feasibility_score', render: percent },
            { title: '客户价值', dataIndex: 'customer_value_score', render: percent },
            { title: '预计收入', dataIndex: 'expected_revenue', render: money },
            { title: '预计成本', dataIndex: 'expected_cost', render: money },
            { title: '预计毛利', dataIndex: 'expected_margin', render: money },
            { title: '推荐', dataIndex: 'recommendation', render: (v) => <StatusTag value={v} /> },
            { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> },
          ]}
        />
      </Spin>
    </>
  );
}
