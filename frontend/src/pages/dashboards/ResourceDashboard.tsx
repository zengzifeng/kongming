import { Button, Form, Input, Select, Spin, Table } from 'antd';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { JsonBlock } from '../../components/JsonBlock';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { dashboardsApi, monitorApi, vendorsApi, watchedClustersApi } from '../../api/kongming';


import { useAsync } from '../../hooks/useAsync';
import { numberText, percent } from '../../utils/format';
import { isWatchedCluster, watchedClusterNames } from '../../utils/watchedClusters';

import type { ResourceNode, VendorQuota } from '../../api/types';

function timeLabel(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function mergeRuntimeRows<T>(items: T[], nameOf: (item: T) => string, timeOf: (item: T) => string, valueOf: (item: T) => number) {
  const byTime = new Map<string, Record<string, string | number>>();
  items.forEach((item) => {
    const time = timeLabel(timeOf(item));
    const row = byTime.get(time) || { time };
    row[nameOf(item)] = Number(row[nameOf(item)] || 0) + valueOf(item);
    byTime.set(time, row);
  });
  return Array.from(byTime.values());
}

export function ResourceDashboard() {


  const [resourceQuery, setResourceQuery] = useState<{ gpu_model?: string; datacenter?: string }>({});
  const [vendorQuery, setVendorQuery] = useState({ page: 1, page_size: 20 });
  const resources = useAsync(() => dashboardsApi.resources(resourceQuery), [resourceQuery.gpu_model, resourceQuery.datacenter]);
  const vendors = useAsync(() => vendorsApi.quotas(vendorQuery), [JSON.stringify(vendorQuery)]);
  const clusterTpm = useAsync(() => monitorApi.clusterTpm(), []);
  const consumerTpm = useAsync(() => monitorApi.consumerTpm(), []);
  const watchedClusters = useAsync(() => watchedClustersApi.list(), []);
  const watchedNames = watchedClusterNames(watchedClusters.data);
  const resourceNodes = (resources.data?.nodes || []).filter((node) => isWatchedCluster(String(node.cluster_name || node.node_id || ''), watchedNames));
  const clusterTpmItems = (clusterTpm.data?.items || []).filter((item) => isWatchedCluster(item.cluster_name, watchedNames));
  const clusterRuntimeData = mergeRuntimeRows(clusterTpmItems, (item) => item.cluster_name, (item) => item.data_time, (item) => Number(item.tpm || 0));

  const modelRuntimeData = mergeRuntimeRows(consumerTpm.data?.items || [], (item) => item.ai_model, (item) => item.data_time, (item) => Number(item.tpm || 0));

  const clusterRuntimeLines = clusterTpmItems.slice(0, 6).map((item, index) => ({ key: item.cluster_name, color: ['#27d7ff', '#ffb347', '#5dffb2', '#9b8cff', '#ff8ab3', '#6aa7ff'][index % 6] }));
  const modelRuntimeLines = (consumerTpm.data?.items || []).slice(0, 6).map((item, index) => ({ key: item.ai_model, color: ['#5dffb2', '#9b8cff', '#27d7ff', '#ffb347', '#ff8ab3', '#6aa7ff'][index % 6] }));
  const error = resources.error || vendors.error || clusterTpm.error || consumerTpm.error || watchedClusters.error;


  return (

    <>
      <PageHeader eyebrow="Resources" title="资源看板" description="自建集群、三方供应商、集群实跑量与模型实跑量统一展示。" />
      {error ? <ErrorState error={error} onRetry={() => { resources.reload(); vendors.reload(); clusterTpm.reload(); consumerTpm.reload(); watchedClusters.reload(); }} /> : null}


      <div className="wire-grid page-section">
          <section className="wire-card">
            <div className="wire-card-title">自建集群信息</div>
            <Form layout="inline" className="filter-bar compact-filter" onFinish={setResourceQuery}>
              <Form.Item name="gpu_model" label="模型"><Input allowClear /></Form.Item>
              <Form.Item name="datacenter" label="机房"><Input allowClear /></Form.Item>
              <Button htmlType="submit" type="primary">筛选</Button>
            </Form>
            <Spin spinning={resources.loading || watchedClusters.loading}>

              <Table<ResourceNode>
                rowKey="node_id"
                size="small"
                dataSource={resourceNodes}

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
            {clusterRuntimeData.length ? <div className="resource-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={clusterRuntimeData}><XAxis dataKey="time" /><YAxis /><Tooltip />{clusterRuntimeLines.map((line) => <Line key={line.key} type="monotone" dataKey={line.key} stroke={line.color} />)}</LineChart></ResponsiveContainer></div> : <EmptyState />}

          </section>
          <section className="wire-card">
            <div className="wire-card-title">模型实跑量</div>
            <Form layout="inline" className="filter-bar compact-filter"><Form.Item label="时间范围"><Select defaultValue="today" style={{ width: 120 }} options={[{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }]} /></Form.Item><Form.Item label="模型"><Input placeholder="全部" /></Form.Item><Form.Item label="客户"><Input placeholder="全部" /></Form.Item></Form>
            {modelRuntimeData.length ? <div className="resource-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={modelRuntimeData}><XAxis dataKey="time" /><YAxis /><Tooltip />{modelRuntimeLines.map((line) => <Line key={line.key} type="monotone" dataKey={line.key} stroke={line.color} />)}</LineChart></ResponsiveContainer></div> : <EmptyState />}

          </section>
        </div>
    </>
  );
}
