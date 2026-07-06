import { Button, Form, InputNumber, Select, Spin, Table } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { ErrorState } from '../../components/ErrorState';
import { policiesApi } from '../../api/kongming';
import type { Policy } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { money } from '../../utils/format';

export function PolicyListPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState({ page: 1, page_size: 10 });
  const { data, error, loading, reload } = useAsync(() => policiesApi.list(query), [JSON.stringify(query)]);
  return (
    <>
      <PageHeader eyebrow="Policies" title="策略中心" description="查看策略收益、约束与执行状态，进入详情执行接受、重算或取消。" />
      <Form layout="inline" className="filter-bar" onFinish={(values) => setQuery({ ...query, ...values, page: 1 })}>
        <Form.Item name="status" label="状态"><Select allowClear style={{ width: 150 }} options={['draft','accepted','cancelled','recalculating','expired'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="algorithm" label="算法"><Select allowClear style={{ width: 150 }} options={['realtime','time_period'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="policy_run_id" label="运行 ID"><InputNumber min={1} /></Form.Item>
        <Button type="primary" htmlType="submit">筛选</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <Table<Policy>
          rowKey="id"
          dataSource={data?.items || []}
          onRow={(record) => ({ onClick: () => navigate(`/policies/${record.id}`) })}
          pagination={{ current: data?.page || 1, pageSize: data?.page_size || 10, total: data?.total || 0, onChange: (page, pageSize) => setQuery({ ...query, page, page_size: pageSize }) }}
          columns={[
            { title: '策略号', dataIndex: 'policy_no' },
            { title: '算法', dataIndex: 'algorithm' },
            { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> },
            { title: '收入增益', dataIndex: 'expected_revenue_gain', render: money },
            { title: '削峰收益', dataIndex: 'expected_peak_shaving_gain', render: money },
            { title: '低峰收益', dataIndex: 'expected_off_peak_gain', render: money },
          ]}
        />
      </Spin>
    </>
  );
}
