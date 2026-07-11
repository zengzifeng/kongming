import { Button, Form, Input, InputNumber, message, Select, Table } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { dashboardsApi } from '../../api/kongming';
import { PageHeader } from '../../components/PageHeader';
import { numberText, percent } from '../../utils/format';

interface MetricItem {
  label: string;
  value: string;
}

interface SelfHostedClusterRow {
  id: string;
  clusterName: string;
  deployedModel: string;
  provider: string;
  machineCount: number;
  tpmPerMachine: number;
  totalCapacity: number;
  runtimeTpm: number;
  clusterUtilization: number;
  redundantTpm: number;
  redundantMachines: number;
}

interface VendorRuntimeRow {
  id: string;
  vendorName: string;
  modelName: string;
  quotaW: number;
  purchaseDiscount: string;
  onlineRuntime: number;
  redundantRuntime: number;
}

interface DemandAcceptanceRow {
  id: number;
  demandNo: string;
  customerId: number;
  modelName: string;
  expectedTpm: number;
  status: string;
}

interface ChartLine {
  key: string;
  name: string;
  color: string;
}

interface ChartSummaryRow {
  label: string;
  color: string;
  max: string;
  mean: string;
  last: string;
}

interface RuntimeLineChartProps {
  title: string;
  data: Array<Record<string, number | string>>;
  lines: ChartLine[];
  summary: ChartSummaryRow[];
  yDomain: [number, number];
  yTicks: number[];
  yFormatter: (value: number) => string;
}

const baseSelfHostedRows: SelfHostedClusterRow[] = [
  { id: 'DeepSeek-V3.2', clusterName: 'DeepSeek-V3.2', deployedModel: 'DeepSeek-V3.2', provider: 'ksyun-dsv32-qy-10017', machineCount: 9, tpmPerMachine: 260, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'GLM-5.1-FP8', clusterName: 'GLM-5.1-FP8', deployedModel: 'GLM-5.1', provider: 'ksyun-glm5.1-qy-10056', machineCount: 6, tpmPerMachine: 260, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'GLM-5.1-KSCC', clusterName: 'GLM-5.1-KSCC', deployedModel: 'GLM-5.1', provider: 'ksyun-glm5.1-qy-10070', machineCount: 3, tpmPerMachine: 700, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'GLM-5.1-XISHANJU', clusterName: 'GLM-5.1-XISHANJU', deployedModel: 'GLM-5.1', provider: 'ksyun-glm5.1-qy-10068', machineCount: 2, tpmPerMachine: 200, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'GLM-5.2', clusterName: 'GLM-5.2', deployedModel: 'GLM-5.2', provider: 'ksyun-glm5.2-qy-10070', machineCount: 20, tpmPerMachine: 200, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'GLM-5.2-Tencent', clusterName: 'GLM-5.2-Tencent', deployedModel: 'GLM-5.2', provider: 'ksyun-glm5.2-qy-10071', machineCount: 24, tpmPerMachine: 250, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'jl-test', clusterName: 'jl-test', deployedModel: '测试机', provider: '', machineCount: 1, tpmPerMachine: 0, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'Kimi-K2.5-NVFP4-MIHAYOU', clusterName: 'Kimi-K2.5-NVFP4-MIHAYOU', deployedModel: 'Kimi-k2.5', provider: 'ksyun-kimi-k25-qy-10065', machineCount: 8, tpmPerMachine: 250, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'KSCC-TEST', clusterName: 'KSCC-TEST', deployedModel: '测试机', provider: '', machineCount: 2, tpmPerMachine: 0, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'llc-test1', clusterName: 'llc-test1', deployedModel: '测试机', provider: '', machineCount: 1, tpmPerMachine: 0, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'wd-test', clusterName: 'wd-test', deployedModel: '测试机', provider: '', machineCount: 2, tpmPerMachine: 0, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
  { id: 'weilai-test', clusterName: 'weilai-test', deployedModel: '测试机', provider: '', machineCount: 1, tpmPerMachine: 0, runtimeTpm: 0, totalCapacity: 0, clusterUtilization: 0, redundantTpm: 0, redundantMachines: 0 },
];

function normalizeClusterRow(row: SelfHostedClusterRow): SelfHostedClusterRow {
  const totalCapacity = row.machineCount * row.tpmPerMachine;
  const redundantTpm = Math.max(totalCapacity - row.runtimeTpm, 0);
  return {
    ...row,
    totalCapacity,
    redundantTpm,
    clusterUtilization: totalCapacity > 0 ? row.runtimeTpm / totalCapacity : 0,
    redundantMachines: row.tpmPerMachine > 0 ? Math.floor(redundantTpm / row.tpmPerMachine) : 0,
  };
}

function buildClusterRows(rows: SelfHostedClusterRow[]) {
  const computedRows = rows.map(normalizeClusterRow);
  const totalRow = normalizeClusterRow({
    id: 'total',
    clusterName: 'Total',
    deployedModel: '',
    provider: '',
    machineCount: computedRows.reduce((total, row) => total + row.machineCount, 0),
    tpmPerMachine: 0,
    totalCapacity: 0,
    runtimeTpm: computedRows.reduce((total, row) => total + row.runtimeTpm, 0),
    clusterUtilization: 0,
    redundantTpm: 0,
    redundantMachines: computedRows.reduce((total, row) => total + row.redundantMachines, 0),
  });
  totalRow.totalCapacity = computedRows.reduce((total, row) => total + row.totalCapacity, 0);
  totalRow.redundantTpm = computedRows.reduce((total, row) => total + row.redundantTpm, 0);
  totalRow.clusterUtilization = totalRow.totalCapacity > 0 ? totalRow.runtimeTpm / totalRow.totalCapacity : 0;
  return [...computedRows, totalRow];
}

function buildSelfHostedMetrics(rows: SelfHostedClusterRow[]): MetricItem[] {
  const computedRows = rows.map(normalizeClusterRow);
  const machineCount = computedRows.reduce((total, row) => total + row.machineCount, 0);
  const totalCapacity = computedRows.reduce((total, row) => total + row.totalCapacity, 0);
  const runtimeTpm = computedRows.reduce((total, row) => total + row.runtimeTpm, 0);
  const redundantTpm = computedRows.reduce((total, row) => total + row.redundantTpm, 0);
  return [
    { label: '机器台数', value: numberText(machineCount) },
    { label: '总承接能力', value: numberText(totalCapacity) },
    { label: '当前冗余TPM', value: numberText(redundantTpm) },
    { label: '当前利用率', value: percent(totalCapacity > 0 ? runtimeTpm / totalCapacity : 0) },
  ];
}

const vendorMetrics: MetricItem[] = [
  { label: '供应商总量', value: '1' },
  { label: '已分配配额 TPM', value: numberText(1000) },
  { label: '线上实跑量', value: numberText(200) },
  { label: '冗余量', value: numberText(2800) },
];

const vendorRows: VendorRuntimeRow[] = [
  { id: 'baidu-glm51', vendorName: '百度', modelName: 'GLM-5.1', quotaW: 3000, purchaseDiscount: '70%', onlineRuntime: 200, redundantRuntime: 2800 },
];

const demandRows: DemandAcceptanceRow[] = [
  { id: 101, demandNo: 'DR-20260628-001', customerId: 88001, modelName: 'ERNIE-4.5-Turbo', expectedTpm: 420000, status: 'awaiting_approval' },
  { id: 102, demandNo: 'DR-20260628-002', customerId: 88018, modelName: 'ERNIE-Speed-128K', expectedTpm: 260000, status: 'evaluating' },
  { id: 103, demandNo: 'DR-20260627-009', customerId: 88032, modelName: 'Embedding-V2', expectedTpm: 180000, status: 'approved' },
  { id: 104, demandNo: 'DR-20260626-004', customerId: 88045, modelName: 'ERNIE-Lite', expectedTpm: 90000, status: 'pending' },
  { id: 105, demandNo: 'DR-20260625-012', customerId: 88001, modelName: 'ERNIE-4.5-Turbo', expectedTpm: 520000, status: 'live' },
];

const modelTpmData = [
  { time: '22:08', glm52: 520000, glm51: 12000 },
  { time: '22:11', glm52: 4000000, glm51: 42000 },
  { time: '22:15', glm52: 900000, glm51: 18000 },
  { time: '22:20', glm52: 430000, glm51: 11000 },
  { time: '22:28', glm52: 360000, glm51: 8000 },
  { time: '22:35', glm52: 620000, glm51: 6000 },
  { time: '22:42', glm52: 260000, glm51: 3000 },
  { time: '22:47', glm52: 680000, glm51: 1000 },
  { time: '22:52', glm52: 360000, glm51: 0 },
  { time: '22:57', glm52: 640000, glm51: 0 },
  { time: '23:05', glm52: 401000, glm51: 0 },
];

const shareData = [
  { time: '22:08', glm51Self: 100, glm52Self: 100 },
  { time: '22:11', glm51Self: 100, glm52Self: 100 },
  { time: '22:20', glm51Self: 100, glm52Self: 100 },
  { time: '22:35', glm51Self: 100, glm52Self: 100 },
  { time: '22:50', glm51Self: 100, glm52Self: 100 },
  { time: '23:05', glm51Self: 100, glm52Self: 100 },
];

const modelLines: ChartLine[] = [
  { key: 'glm52', name: 'glm-5.2', color: '#f5d54b' },
  { key: 'glm51', name: 'glm-5.1', color: '#5dffb2' },
];

const shareLines: ChartLine[] = [
  { key: 'glm51Self', name: 'glm-5.1 自建', color: '#5dffb2' },
  { key: 'glm52Self', name: 'glm-5.2 自建', color: '#f5d54b' },
];

const demandMetrics: MetricItem[] = [
  { label: '待承接需求', value: numberText(demandRows.filter((item) => ['pending', 'reported', 'evaluating'].includes(item.status)).length) },
  { label: '需求 TPM', value: numberText(demandRows.reduce((total, item) => total + item.expectedTpm, 0)) },
  { label: '自建当前可供 TPM', value: numberText(14880) },
  { label: '三方需求持 TPM', value: numberText(2800) },
];

function formatTpm(value: number) {
  if (value >= 1000000) return `${Number((value / 1000000).toFixed(1))} Mil`;
  if (value >= 1000) return `${Number((value / 1000).toFixed(0))} K`;
  return String(value);
}

function formatPercentAxis(value: number) {
  return `${value.toFixed(2)}%`;
}

function MetricStrip({ items }: { items: MetricItem[] }) {
  return (
    <div className="realtime-metric-strip">
      {items.map((item) => (
        <div className="realtime-metric" key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  );
}

function RuntimeLineChart({ title, data, lines, summary, yDomain, yTicks, yFormatter }: RuntimeLineChartProps) {
  return (
    <div className="realtime-chart-card">
      <div className="realtime-chart-title">{title}</div>
      <div className="realtime-chart-canvas">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -2 }}>
            <CartesianGrid stroke="rgba(82, 191, 255, .12)" strokeDasharray="3 3" />
            <XAxis dataKey="time" axisLine={false} tickLine={false} minTickGap={12} tick={{ fill: '#7898a7', fontSize: 11 }} />
            <YAxis width={44} domain={yDomain} ticks={yTicks} tickFormatter={(value) => yFormatter(Number(value))} axisLine={false} tickLine={false} tick={{ fill: '#7898a7', fontSize: 11 }} />
            <Tooltip contentStyle={{ background: '#071018', border: '1px solid rgba(82, 191, 255, .28)', borderRadius: 8 }} labelStyle={{ color: '#e6f7ff' }} />
            {lines.map((line) => (
              <Line key={line.key} type="monotone" dataKey={line.key} name={line.name} stroke={line.color} strokeWidth={2} dot={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="realtime-chart-summary">
        <span />
        <strong>Max</strong>
        <strong>Mean</strong>
        <strong>Last*</strong>
        {summary.map((item) => (
          <div className="realtime-summary-row" key={item.label}>
            <span className="realtime-legend-label"><i style={{ backgroundColor: item.color }} />{item.label}</span>
            <span>{item.max}</span>
            <span>{item.mean}</span>
            <span>{item.last}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RealtimeDashboard() {
  const navigate = useNavigate();
  const [selfHostedRows, setSelfHostedRows] = useState<SelfHostedClusterRow[]>(() => baseSelfHostedRows.map(normalizeClusterRow));
  const [savingClusterId, setSavingClusterId] = useState<string | null>(null);
  const selfHostedTableRows = useMemo(() => buildClusterRows(selfHostedRows), [selfHostedRows]);
  const selfHostedMetrics = useMemo(() => buildSelfHostedMetrics(selfHostedRows), [selfHostedRows]);

  useEffect(() => {
    let cancelled = false;
    dashboardsApi.resources({}).then((data) => {
      if (cancelled || !data.clusters?.length) return;
      setSelfHostedRows((rows) => rows.map((row) => {
        const cluster = data.clusters?.find((item) => item.cluster_name === row.clusterName && item.deployed_model === row.deployedModel);
        if (!cluster) return row;
        return normalizeClusterRow({
          ...row,
          provider: cluster.provider || row.provider,
          machineCount: Number(cluster.machine_count ?? row.machineCount),
          tpmPerMachine: Number(cluster.tpm_per_machine_w ?? row.tpmPerMachine),
          runtimeTpm: Number(cluster.current_tpm_w ?? row.runtimeTpm),
        });
      }));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const saveTpmPerMachine = async (record: SelfHostedClusterRow, value: number | null) => {
    const nextValue = Number(value || 0);
    if (nextValue === record.tpmPerMachine) return;
    const nextRow = normalizeClusterRow({ ...record, tpmPerMachine: nextValue });
    setSavingClusterId(record.id);
    try {
      await dashboardsApi.updateClusterResource({
        cluster_name: record.clusterName,
        deployed_model: record.deployedModel,
        provider: record.provider,
        machine_count: record.machineCount,
        tpm_per_machine_w: nextValue,
        current_tpm_w: record.runtimeTpm,
      });
      setSelfHostedRows((rows) => rows.map((row) => (row.id === record.id ? nextRow : row)));
      message.success('单机承载能力已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '单机承载能力保存失败');
    } finally {
      setSavingClusterId(null);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Realtime" title="实时看板" description="展示当前自建资源、三方供应商、模型与客户维度实跑，以及新需求承接能力。" />
      <div className="realtime-board page-section">
        <section className="wire-card realtime-panel realtime-cluster-panel">
          <div className="wire-card-title">自建集群信息</div>
          <MetricStrip items={selfHostedMetrics} />
          <Table<SelfHostedClusterRow>
            rowKey="id"
            size="small"
            dataSource={selfHostedTableRows}
            pagination={false}
            scroll={{ x: 1180 }}
            rowClassName={(record) => (record.id === 'total' ? 'realtime-total-row' : '')}
            columns={[
              { title: '集群名称', dataIndex: 'clusterName', width: 190 },
              { title: '主要部署模型', dataIndex: 'deployedModel', width: 150 },
              { title: 'provider', dataIndex: 'provider', width: 190 },
              { title: '机器台数', dataIndex: 'machineCount', width: 90, align: 'right', render: numberText },
              {
                title: '单机承载能力',
                dataIndex: 'tpmPerMachine',
                width: 130,
                align: 'right',
                render: (value, record) => record.id === 'total' ? '' : (
                  <InputNumber
                    key={`${record.id}-${value}`}
                    className="realtime-cell-number"
                    min={0}
                    size="small"
                    defaultValue={Number(value || 0)}
                    disabled={savingClusterId === record.id}
                    onPressEnter={(event) => event.currentTarget.blur()}
                    onBlur={(event) => saveTpmPerMachine(record, Number(event.currentTarget.value))}
                  />
                ),
              },
              { title: '总承载能力', dataIndex: 'totalCapacity', width: 110, align: 'right', render: numberText },
              { title: '实跑TPM', dataIndex: 'runtimeTpm', width: 100, align: 'right', render: numberText },
              { title: '集群利用率', dataIndex: 'clusterUtilization', width: 100, align: 'right', render: percent },
              { title: '冗余TPM', dataIndex: 'redundantTpm', width: 100, align: 'right', render: numberText },
              { title: '冗余机器台数', dataIndex: 'redundantMachines', width: 120, align: 'right', render: numberText },
            ]}
          />
        </section>

        <section className="wire-card realtime-panel realtime-vendor-panel">
          <div className="wire-card-title">三方供应商信息</div>
          <MetricStrip items={vendorMetrics} />
          <Table<VendorRuntimeRow>
            rowKey="id"
            size="small"
            dataSource={vendorRows}
            pagination={false}
            scroll={{ x: 760 }}
            expandable={{ expandedRowRender: (record) => <div className="realtime-expand-note">当前冗余量：{numberText(record.redundantRuntime)}w TPM</div> }}
            columns={[
              { title: '供应商名称', dataIndex: 'vendorName', width: 120 },
              { title: '模型名称', dataIndex: 'modelName', width: 120 },
              { title: '配额（w）', dataIndex: 'quotaW', width: 110, render: numberText },
              { title: '采购折扣', dataIndex: 'purchaseDiscount', width: 100 },
              { title: '线上实际能量', dataIndex: 'onlineRuntime', width: 120, render: numberText },
              { title: '已冗余量', dataIndex: 'redundantRuntime', width: 100, render: numberText },
            ]}
          />
        </section>

        <section className="wire-card realtime-panel realtime-runtime-panel">
          <div className="wire-card-title">模型/客户维度实跑图</div>
          <Form layout="inline" className="realtime-filter-grid">
            <Form.Item label="时间范围"><Select defaultValue="today" options={[{ label: '今日', value: 'today' }, { label: '近 7 天', value: '7d' }]} /></Form.Item>
            <Form.Item label="模型"><Input defaultValue="全部" /></Form.Item>
            <Form.Item label="客户"><Input defaultValue="全部" /></Form.Item>
            <Form.Item label="用户ID"><Input defaultValue="全部" /></Form.Item>
          </Form>
          <div className="realtime-chart-stack">
            <RuntimeLineChart
              title="售卖模型TPM(BODHIMIND SDN.BHD.)"
              data={modelTpmData}
              lines={modelLines}
              yDomain={[0, 4200000]}
              yTicks={[0, 1000000, 2000000, 4000000]}
              yFormatter={formatTpm}
              summary={[
                { label: 'glm-5.2', color: '#f5d54b', max: '4 Mil', mean: '801 K', last: '401 K' },
                { label: 'glm-5.1', color: '#5dffb2', max: '42 K', mean: '6 K', last: '0' },
              ]}
            />
            <RuntimeLineChart
              title="售卖模型分发后端TPM占比(自建第三方维度，BODHIMIND SDN.BHD.)"
              data={shareData}
              lines={shareLines}
              yDomain={[0, 200]}
              yTicks={[0, 50, 100, 150, 200]}
              yFormatter={formatPercentAxis}
              summary={[
                { label: 'glm-5.1 自建', color: '#5dffb2', max: '100.00%', mean: '100.00%', last: '100.00%' },
                { label: 'glm-5.2 自建', color: '#f5d54b', max: '100.00%', mean: '100.00%', last: '100.00%' },
              ]}
            />
            <RuntimeLineChart
              title="售卖模型分发后端TPM占比(模型维度，BODHIMIND SDN.BHD.)"
              data={shareData}
              lines={shareLines}
              yDomain={[0, 200]}
              yTicks={[0, 50, 100, 150, 200]}
              yFormatter={formatPercentAxis}
              summary={[
                { label: 'glm-5.1 自建', color: '#5dffb2', max: '100.00%', mean: '100.00%', last: '100.00%' },
                { label: 'glm-5.2 自建', color: '#f5d54b', max: '100.00%', mean: '100.00%', last: '100.00%' },
              ]}
            />
          </div>
        </section>

        <section className="wire-card realtime-panel realtime-demand-panel">
          <div className="realtime-title-row">
            <div className="wire-card-title">新需求承接信息</div>
            <Button type="primary" size="small" onClick={() => navigate('/demands')}>录入需求</Button>
          </div>
          <MetricStrip items={demandMetrics} />
          <Table<DemandAcceptanceRow>
            rowKey="id"
            size="small"
            dataSource={demandRows}
            pagination={false}
            scroll={{ x: 620 }}
            columns={[
              { title: '需求', dataIndex: 'demandNo', width: 150 },
              { title: '客户', dataIndex: 'customerId', width: 86 },
              {
                title: '操作',
                key: 'actions',
                width: 260,
                render: (_, record) => (
                  <div className="realtime-action-group">
                    <Button size="small" onClick={() => navigate(`/demands/${record.id}`)}>查看</Button>
                    <Button size="small" onClick={() => navigate(`/demands/${record.id}`)}>发起评估</Button>
                    <Button size="small" onClick={() => navigate('/demands')}>状态流转</Button>
                  </div>
                ),
              },
            ]}
          />
        </section>
      </div>
    </>
  );
}
