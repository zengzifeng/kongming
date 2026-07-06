import { Button, Form, Input, Progress, Select, Spin, Table } from 'antd';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Line, LineChart, XAxis, YAxis } from 'recharts';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { JsonBlock } from '../../components/JsonBlock';
import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { dashboardsApi, demandsApi, vendorsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { numberText, percent } from '../../utils/format';
import type { Demand, ResourceNode, VendorQuota } from '../../api/types';

const modelRuntimeMock = [
  { time: '09:00', model: 220, customer: 180, selfHosted: 260, thirdParty: 140 },
  { time: '11:00', model: 380, customer: 260, selfHosted: 430, thirdParty: 210 },
  { time: '13:00', model: 330, customer: 420, selfHosted: 470, thirdParty: 280 },
  { time: '15:00', model: 520, customer: 390, selfHosted: 590, thirdParty: 320 },
  { time: '17:00', model: 610, customer: 470, selfHosted: 690, thirdParty: 390 },
];

const routeShare = [
  { name: '自建路由', value: 64 },
  { name: '三方路由', value: 36 },
];

const vendorShare = [
  { name: '火山', value: 38 },
  { name: '百舸', value: 31 },
  { name: '千帆', value: 21 },
  { name: '其他', value: 10 },
];

const palette = ['#27d7ff', '#5dffb2', '#ffb347', '#9b8cff', '#ff5f6d'];

function sum<T>(items: T[], pick: (item: T) => number | null | undefined) {
  return items.reduce((total, item) => total + Number(pick(item) || 0), 0);
}

interface ClusterCapacityRow {
  clusterName: string;
  model: string;
  customers: string;
  machineCount: number;
  singleMachineTpm: number;
  totalCapacity: number;
  currentTpm: number;
  utilization: number;
  redundantMachines: number;
}

function buildClusterRows(nodes: ResourceNode[], demands: Demand[]): ClusterCapacityRow[] {
  const customerByModel = demands.reduce<Record<string, Set<string>>>((map, demand) => {
    const key = demand.model_name || '未知模型';
    if (!map[key]) map[key] = new Set<string>();
    if (demand.customer_id) map[key].add(`客户 ${demand.customer_id}`);
    return map;
  }, {});

  return nodes.map((node) => {
    const machineCount = Number(node.machine_count || node.machine_num || node.gpu_count || node.device_count || 1);
    const totalCapacity = Number(node.capacity_tpm || 0);
    const availableTpm = Number(node.available_tpm || 0);
    const currentTpm = Math.max(totalCapacity - availableTpm, 0);
    const singleMachineTpm = machineCount > 0 ? Math.floor(totalCapacity / machineCount) : totalCapacity;
    const utilization = totalCapacity > 0 ? currentTpm / totalCapacity : Number(node.utilization || 0);
    const customers = Array.from(customerByModel[node.gpu_model] || []).slice(0, 3).join('、') || '通用客户';

    return {
      clusterName: String(node.cluster_name || node.cluster || node.node_id),
      model: node.gpu_model,
      customers,
      machineCount,
      singleMachineTpm,
      totalCapacity,
      currentTpm,
      utilization,
      redundantMachines: singleMachineTpm > 0 ? Math.floor(availableTpm / singleMachineTpm) : 0,
    };
  });
}

export function RealtimeDashboard() {
  const [resourceQuery, setResourceQuery] = useState<{ gpu_model?: string; datacenter?: string }>({});
  const [vendorQuery, setVendorQuery] = useState({ page: 1, page_size: 20 });
  const resources = useAsync(() => dashboardsApi.resources(resourceQuery), [resourceQuery.gpu_model, resourceQuery.datacenter]);
  const vendors = useAsync(() => vendorsApi.quotas(vendorQuery), [JSON.stringify(vendorQuery)]);
  const demands = useAsync(() => demandsApi.list({ page: 1, page_size: 50 }), []);
  const error = resources.error || vendors.error || demands.error;

  const nodes = resources.data?.nodes || [];
  const vendorItems = vendors.data?.items || [];
  const demandItems = demands.data?.items || [];
  const totalCapacity = resources.data?.total_capacity_tpm ?? sum(nodes, (item) => item.capacity_tpm);
  const totalAvailable = resources.data?.total_available_tpm ?? sum(nodes, (item) => item.available_tpm);
  const vendorQuota = sum(vendorItems, (item) => item.quota_tpm);
  const onlineRuntime = 12600;
  const pendingDemands = demandItems.filter((item) => ['pending', 'reported', 'evaluating'].includes(item.status)).length;
  const demandTpm = sum(demandItems, (item) => item.expected_tpm);
  const thirdPartyHoldTpm = Math.max(vendorQuota - onlineRuntime, 0);
  const clusterRows = useMemo(() => buildClusterRows(nodes, demandItems), [nodes, demandItems]);

  const modelRuntime = useMemo(() => modelRuntimeMock, []);

  return (
    <>
      <PageHeader eyebrow="Realtime" title="实时看板" description="展示当前自建资源、三方供应商、模型与客户维度实跑，以及新需求承接能力。" />
      {error ? <ErrorState error={error} onRetry={() => { resources.reload(); vendors.reload(); demands.reload(); }} /> : null}
      <div className="wire-grid page-section">
        <section className="wire-card dashboard-panel-wide">
          <div className="wire-card-title">自建集群信息</div>
          <div className="metric-strip">
            <div><span>机器台数</span><strong>{numberText(nodes.length)}</strong></div>
            <div><span>总容量 TPM</span><strong>{numberText(totalCapacity)}</strong></div>
            <div><span>可供 TPM</span><strong>{numberText(totalAvailable)}</strong></div>
            <div><span>实时利用率</span><strong>{percent(resources.data?.avg_utilization)}</strong></div>
          </div>
          <Form layout="inline" className="filter-bar compact-filter" onFinish={setResourceQuery}>
            <Form.Item name="gpu_model" label="模型"><Input allowClear /></Form.Item>
            <Form.Item name="datacenter" label="机房"><Input allowClear /></Form.Item>
            <Button htmlType="submit" type="primary">筛选</Button>
          </Form>
          <Spin spinning={resources.loading}>
            <Table<ClusterCapacityRow>
              rowKey="clusterName"
              size="small"
              dataSource={clusterRows}
              pagination={{ pageSize: 5 }}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: '集群名称', dataIndex: 'clusterName' },
                { title: '部署模型', dataIndex: 'model' },
                { title: '主要支持客户', dataIndex: 'customers' },
                { title: '机器数量', dataIndex: 'machineCount', render: numberText },
                { title: '单台承接 TPM', dataIndex: 'singleMachineTpm', render: numberText },
                { title: '总承接能力', dataIndex: 'totalCapacity', render: numberText },
                { title: '当前 TPM', dataIndex: 'currentTpm', render: numberText },
                { title: '当前利用率', dataIndex: 'utilization', render: (value) => <Progress percent={Number((Number(value || 0) * 100).toFixed(1))} size="small" strokeColor="#27d7ff" /> },
                { title: '当前冗余台数', dataIndex: 'redundantMachines', render: numberText },
              ]}
            />
          </Spin>
        </section>

        <section className="wire-card dashboard-panel-wide">
          <div className="wire-card-title">三方供应商信息</div>
          <div className="metric-strip">
            <div><span>供应商总量</span><strong>{numberText(vendors.data?.total || 0)}</strong></div>
            <div><span>已分配配额 TPM</span><strong>{numberText(vendorQuota)}</strong></div>
            <div><span>线上实跑量</span><strong>{numberText(onlineRuntime)}</strong></div>
            <div><span>冗余量</span><strong>{numberText(thirdPartyHoldTpm)}</strong></div>
          </div>
          <Spin spinning={vendors.loading}>
            <Table<VendorQuota>
              rowKey="id"
              size="small"
              dataSource={vendorItems}
              expandable={{ expandedRowRender: (record) => <JsonBlock value={record} /> }}
              pagination={{ current: vendors.data?.page || 1, pageSize: vendors.data?.page_size || 20, total: vendors.data?.total || 0, onChange: (page, pageSize) => setVendorQuery({ page, page_size: pageSize }) }}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: '供应商', dataIndex: 'vendor' },
                { title: '模型', dataIndex: 'model' },
                { title: '配额 TPM', dataIndex: 'quota_tpm', render: numberText },
                { title: '采购折扣', dataIndex: 'unit_cost' },
                { title: '状态', dataIndex: 'status' },
              ]}
            />
          </Spin>
        </section>

        <section className="wire-card dashboard-panel-wide">
          <div className="wire-card-title">模型/客户维度实跑图</div>
          <Form layout="inline" className="filter-bar compact-filter">
            <Form.Item label="时间范围"><Select defaultValue="today" style={{ width: 120 }} options={[{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }]} /></Form.Item>
            <Form.Item label="模型"><Input placeholder="全部" /></Form.Item>
            <Form.Item label="客户"><Input placeholder="全部" /></Form.Item>
          </Form>
          {modelRuntime.length ? (
            <div className="split-panel runtime-panel">
              <div className="resource-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={modelRuntime}>
                    <XAxis dataKey="time" />
                    <YAxis />
                    <Tooltip />
                    <Line type="monotone" dataKey="model" name="模型实跑" stroke="#5dffb2" />
                    <Line type="monotone" dataKey="customer" name="客户实跑" stroke="#9b8cff" />
                    <Line type="monotone" dataKey="selfHosted" name="自建分发" stroke="#27d7ff" />
                    <Line type="monotone" dataKey="thirdParty" name="三方分发" stroke="#ffb347" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="share-column">
                <ResponsiveContainer width="100%" height={150}><PieChart><Pie data={routeShare} dataKey="value" nameKey="name" innerRadius={36} outerRadius={58}>{routeShare.map((_, index) => <Cell key={index} fill={palette[index % palette.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
                <ResponsiveContainer width="100%" height={150}><PieChart><Pie data={vendorShare} dataKey="value" nameKey="name" innerRadius={34} outerRadius={56}>{vendorShare.map((_, index) => <Cell key={index} fill={palette[(index + 2) % palette.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
              </div>
            </div>
          ) : <EmptyState />}
        </section>

        <section className="wire-card">
          <div className="wire-card-title">新需求承接信息</div>
          <Spin spinning={demands.loading}>
            <div className="acceptance-grid">
              <div><span>待承接需求</span><strong>{numberText(pendingDemands)}</strong></div>
              <div><span>需求 TPM</span><strong>{numberText(demandTpm)}</strong></div>
              <div><span>自建当前可供 TPM</span><strong>{numberText(totalAvailable)}</strong></div>
              <div><span>三方需求持 TPM</span><strong>{numberText(thirdPartyHoldTpm)}</strong></div>
            </div>
            <Table<Demand>
              rowKey="id"
              size="small"
              dataSource={demandItems.slice(0, 6)}
              pagination={false}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: '需求', dataIndex: 'report_id' },
                { title: '客户', dataIndex: 'customer_id' },
                { title: '模型', dataIndex: 'model_name' },
                { title: '需求 TPM', dataIndex: 'expected_tpm', render: numberText },
                { title: '状态', dataIndex: 'status' },
              ]}
            />
          </Spin>
        </section>
      </div>
    </>
  );
}
