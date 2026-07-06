import { Button, Form, Input, Select, Spin, Table } from 'antd';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { JsonBlock } from '../../components/JsonBlock';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { dashboardsApi, vendorsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { numberText, percent } from '../../utils/format';
import type { ResourceNode, VendorQuota } from '../../api/types';

const clusterMock = [
  { time: '09:00', clusterA: 320, clusterB: 280 },
  { time: '11:00', clusterA: 520, clusterB: 410 },
  { time: '13:00', clusterA: 460, clusterB: 610 },
  { time: '15:00', clusterA: 700, clusterB: 540 },
  { time: '17:00', clusterA: 640, clusterB: 760 },
];

const modelMock = [
  { time: '09:00', realtime: 220, batch: 180 },
  { time: '11:00', realtime: 380, batch: 260 },
  { time: '13:00', realtime: 330, batch: 420 },
  { time: '15:00', realtime: 520, batch: 390 },
  { time: '17:00', realtime: 610, batch: 470 },
];

export function ResourceDashboard() {
  const [resourceQuery, setResourceQuery] = useState<{ gpu_model?: string; datacenter?: string }>({});
  const [vendorQuery, setVendorQuery] = useState({ page: 1, page_size: 20 });
  const resources = useAsync(() => dashboardsApi.resources(resourceQuery), [resourceQuery.gpu_model, resourceQuery.datacenter]);
  const vendors = useAsync(() => vendorsApi.quotas(vendorQuery), [JSON.stringify(vendorQuery)]);
  const error = resources.error || vendors.error;

  return (
    <>
      <PageHeader eyebrow="Resources" title="资源看板" description="自建集群、三方供应商、集群实跑量与模型实跑量统一展示。" />
      {error ? <ErrorState error={error} onRetry={() => { resources.reload(); vendors.reload(); }} /> : null}
      <div className="wire-grid page-section">
          <section className="wire-card">
            <div className="wire-card-title">自建集群信息</div>
            <Form layout="inline" className="filter-bar compact-filter" onFinish={setResourceQuery}>
              <Form.Item name="gpu_model" label="模型"><Input allowClear /></Form.Item>
              <Form.Item name="datacenter" label="机房"><Input allowClear /></Form.Item>
              <Button htmlType="submit" type="primary">筛选</Button>
            </Form>
            <Spin spinning={resources.loading}>
              <Table<ResourceNode>
                rowKey="node_id"
                size="small"
                dataSource={resources.data?.nodes || []}
                expandable={{ expandedRowRender: (record) => <JsonBlock value={record} /> }}
                pagination={{ pageSize: 5 }}
                scroll={{ x: 'max-content' }}
                columns={[
                  { title: '节点', dataIndex: 'node_id' },
                  { title: '模型', dataIndex: 'gpu_model' },
                  { title: '机房', dataIndex: 'datacenter' },
                  { title: 'AZ', dataIndex: 'az' },
                  { title: '容量 TPM', dataIndex: 'capacity_tpm', render: numberText },
                  { title: '可用 TPM', dataIndex: 'available_tpm', render: numberText },
                  { title: '利用率', dataIndex: 'utilization', render: percent },
                ]}
              />
            </Spin>
          </section>
          <section className="wire-card">
            <div className="wire-card-title">三方供应商信息</div>
            <Spin spinning={vendors.loading}>
              <Table<VendorQuota>
                rowKey="id"
                size="small"
                dataSource={vendors.data?.items || []}
                expandable={{ expandedRowRender: (record) => <JsonBlock value={record} /> }}
                pagination={{ current: vendors.data?.page || 1, pageSize: vendors.data?.page_size || 20, total: vendors.data?.total || 0, onChange: (page, pageSize) => setVendorQuery({ page, page_size: pageSize }) }}
                scroll={{ x: 'max-content' }}
                columns={[
                  { title: '供应商', dataIndex: 'vendor' },
                  { title: '模型', dataIndex: 'model' },
                  { title: '配额 TPM', dataIndex: 'quota_tpm', render: numberText },
                  { title: '成本', dataIndex: 'unit_cost' },
                  { title: '价格', dataIndex: 'unit_price' },
                  { title: '状态', dataIndex: 'status' },
                  { title: '联系人', dataIndex: 'contact' },
                ]}
              />
            </Spin>
          </section>
          <section className="wire-card">
            <div className="wire-card-title">集群实跑量</div>
            <Form layout="inline" className="filter-bar compact-filter"><Form.Item label="时间范围"><Select defaultValue="today" style={{ width: 140 }} options={[{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }]} /></Form.Item></Form>
            <div className="resource-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={clusterMock}><XAxis dataKey="time" /><YAxis /><Tooltip /><Line type="monotone" dataKey="clusterA" stroke="#27d7ff" /><Line type="monotone" dataKey="clusterB" stroke="#ffb347" /></LineChart></ResponsiveContainer></div>
          </section>
          <section className="wire-card">
            <div className="wire-card-title">模型实跑量</div>
            <Form layout="inline" className="filter-bar compact-filter"><Form.Item label="时间范围"><Select defaultValue="today" style={{ width: 120 }} options={[{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }]} /></Form.Item><Form.Item label="模型"><Input placeholder="全部" /></Form.Item><Form.Item label="客户"><Input placeholder="全部" /></Form.Item></Form>
            {modelMock.length ? <div className="resource-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={modelMock}><XAxis dataKey="time" /><YAxis /><Tooltip /><Line type="monotone" dataKey="realtime" stroke="#5dffb2" /><Line type="monotone" dataKey="batch" stroke="#9b8cff" /></LineChart></ResponsiveContainer></div> : <EmptyState />}
          </section>
        </div>
    </>
  );
}
