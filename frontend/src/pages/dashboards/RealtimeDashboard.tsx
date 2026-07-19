import { Button, DatePicker, Form, InputNumber, message, Select } from 'antd';

import { CheckOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { dashboardsApi, fittingsApi, monitorApi, vendorsApi, watchedClustersApi } from '../../api/kongming';

import type { ConsumerTpmSnapshot, FittingResult, ResourceCluster, VendorQuota } from '../../api/types';

import { PageHeader } from '../../components/PageHeader';
import { numberText, percent } from '../../utils/format';
import { isWatchedCluster, watchedClusterNames } from '../../utils/watchedClusters';

interface MetricItem {

  label: string;
  value: string;
}

type ResourcePeriod = 'realtime' | 'idle' | 'busy';

interface SelfHostedClusterRow {
  id: string;
  clusterName: string;
  deployedModel: string;
  provider: string;
  machineCount: number;
  tpmPerMachine: number;
  totalCapacity: number;
  runtimeTpm: number;
  realtimeRuntimeTpm?: number;
  idleRuntimeTpm?: number;
  busyRuntimeTpm?: number;
  clusterUtilization: number;
  redundantTpm: number;
  redundantMachines: number;
}

interface VendorRuntimeRow {
  id: string;
  vendorName: string;
  providerName: string;
  modelName: string;
  quotaW: number;
  purchaseDiscount: number;
  purchaseDiscountText: string;
  onlineRuntime: number;
  redundantRuntime: number;
  runtimeRatio: number;
}

interface ChartLine {

  key: string;
  name: string;
  color: string;
}

interface FitWaveLine extends ChartLine {
  strokeDasharray?: string;
}

interface CustomerWatermark {
  key: string;
  name: string;
  color: string;
  peakDemand: number;
  selfWatermark: number;
  vendorTakeover: number;
}


interface CustomerDispatchRatio {
  key: string;
  name: string;
  color: string;
  selfRatio: number;
  vendorRatio: number;
}

interface CustomerFitWave {

  model: string;
  data: Array<Record<string, number | string>>;
  lines: FitWaveLine[];
  ratios: CustomerDispatchRatio[];
  yDomain: [number, number];
  yTicks: number[];
}

interface ConsumerTpmFilterOptions {
  aiModels: string[];
  aiConsumers: string[];
  customerCodes: string[];
}

interface ConsumerTpmFilters {
  range: [Dayjs, Dayjs] | null;
  aiModel?: string;
  aiConsumer?: string;
  customerCode?: string;
}

interface ChartSummaryRow {
  label: string;
  color: string;
  max: string;
  mean: string;
  last: string;
}

interface ChartReferenceLine extends FitWaveLine {
  value: number;
}

interface RuntimeLineChartProps {
  title: string;
  data: Array<Record<string, number | string>>;
  lines: FitWaveLine[];
  summary?: ChartSummaryRow[];
  yDomain: [number, number];
  yTicks: number[];
  yFormatter: (value: number) => string;
  tooltipFormatter?: (value: number) => string;
  // tooltip 只渲染这一条线（选中某集群后悬浮只显示该集群的值）；为空时显示全部线。
  tooltipSingleKey?: string | null;
  selectedLineKey?: string | null;
  hoveredLineKey?: string | null;
  legendRenderer?: () => ReactNode;
  referenceLines?: ChartReferenceLine[];
  onLineClick?: (key: string) => void;
  forceSolidLines?: boolean;
}



interface VendorModelGroup {
  modelName: string;
  rows: VendorRuntimeRow[];
  quotaW: number;
  onlineRuntime: number;
  redundantRuntime: number;
  runtimeRatio: number;
}


interface CapacityBarShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: SelfHostedClusterRow;
}


const chartColors = ['#27d7ff', '#5dffb2', '#f5d54b', '#9b8cff', '#ff8ab3', '#6aa7ff', '#ff6b6b', '#42d4f4', '#c19a6b'];
const defaultConsumerTpmRange = (): [Dayjs, Dayjs] => [dayjs().startOf('day'), dayjs().endOf('day')];
const emptyConsumerTpmOptions = (): ConsumerTpmFilterOptions => ({ aiModels: [], aiConsumers: [], customerCodes: [] });

function selectOptions(items: string[]) {
  return items.map((item) => ({ label: item, value: item }));
}

function timeLabel(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function mapResourceCluster(cluster: ResourceCluster): SelfHostedClusterRow {
  const row = {
    id: `${cluster.cluster_name}-${cluster.deployed_model}`,
    clusterName: cluster.cluster_name,
    deployedModel: cluster.deployed_model,
    provider: cluster.provider || '',
    machineCount: Number(cluster.machine_count || 0),
    tpmPerMachine: Number(cluster.tpm_per_machine_w ?? toWanTpm(cluster.tpm_per_machine)),
    totalCapacity: Number(cluster.total_capacity_w ?? toWanTpm(cluster.total_capacity_tpm)),
    runtimeTpm: Number(cluster.current_tpm_w ?? toWanTpm(cluster.current_tpm)),
    realtimeRuntimeTpm: Number(cluster.current_tpm_w ?? toWanTpm(cluster.current_tpm)),
    idleRuntimeTpm: Number(cluster.peak_tpm_idle !== undefined ? toWanTpm(cluster.peak_tpm_idle) : cluster.current_tpm_w ?? toWanTpm(cluster.current_tpm)),
    busyRuntimeTpm: Number(cluster.peak_tpm_busy !== undefined ? toWanTpm(cluster.peak_tpm_busy) : cluster.current_tpm_w ?? toWanTpm(cluster.current_tpm)),
    clusterUtilization: Number(cluster.cluster_utilization || 0),
    redundantTpm: Number(cluster.current_redundant_w ?? toWanTpm(cluster.current_redundant_tpm)),
    redundantMachines: Number(cluster.current_redundant_machines || 0),
  };
  return normalizeClusterRow(row);
}


function runtimeForPeriod(row: SelfHostedClusterRow, period: ResourcePeriod) {
  if (period === 'idle') return Number(row.idleRuntimeTpm ?? row.runtimeTpm);
  if (period === 'busy') return Number(row.busyRuntimeTpm ?? row.runtimeTpm);
  return Number(row.realtimeRuntimeTpm ?? row.runtimeTpm);
}

function deriveClusterRowForPeriod(row: SelfHostedClusterRow, period: ResourcePeriod): SelfHostedClusterRow {
  const totalCapacity = row.machineCount * row.tpmPerMachine;
  const runtimeTpm = runtimeForPeriod(row, period);
  const redundantTpm = Math.max(totalCapacity - runtimeTpm, 0);
  return {
    ...row,
    runtimeTpm,
    totalCapacity,
    redundantTpm,
    clusterUtilization: totalCapacity > 0 ? runtimeTpm / totalCapacity : 0,
    redundantMachines: row.tpmPerMachine > 0 ? Math.floor(redundantTpm / row.tpmPerMachine) : 0,
  };
}

function normalizeClusterRow(row: SelfHostedClusterRow): SelfHostedClusterRow {
  return deriveClusterRowForPeriod(row, 'realtime');
}

function buildClusterRows(rows: SelfHostedClusterRow[], period: ResourcePeriod = 'realtime') {
  const computedRows = rows.map((row) => deriveClusterRowForPeriod(row, period));
  const totalRow = deriveClusterRowForPeriod({
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
  }, period);
  totalRow.totalCapacity = computedRows.reduce((total, row) => total + row.totalCapacity, 0);
  totalRow.redundantTpm = computedRows.reduce((total, row) => total + row.redundantTpm, 0);
  totalRow.clusterUtilization = totalRow.totalCapacity > 0 ? totalRow.runtimeTpm / totalRow.totalCapacity : 0;
  return [...computedRows, totalRow];
}

function buildSelfHostedMetrics(rows: SelfHostedClusterRow[], period: ResourcePeriod = 'realtime'): MetricItem[] {
  const computedRows = rows.map((row) => deriveClusterRowForPeriod(row, period));
  const machineCount = computedRows.reduce((total, row) => total + row.machineCount, 0);
  const totalCapacity = computedRows.reduce((total, row) => total + row.totalCapacity, 0);
  const runtimeTpm = computedRows.reduce((total, row) => total + row.runtimeTpm, 0);
  const redundantTpm = computedRows.reduce((total, row) => total + row.redundantTpm, 0);
  return [
    { label: '机器台数', value: numberText(machineCount) },
    { label: '总承接能力', value: numberText(totalCapacity) },
    { label: '冗余TPM', value: numberText(redundantTpm) },
    { label: '利用率', value: percent(totalCapacity > 0 ? runtimeTpm / totalCapacity : 0) },
  ];
}

function mergeClusterResponse(row: SelfHostedClusterRow, cluster: ResourceCluster): SelfHostedClusterRow {
  const nextRow = {
    ...row,
    provider: cluster.provider || row.provider,
    machineCount: Number(cluster.machine_count ?? row.machineCount),
    tpmPerMachine: Number(cluster.tpm_per_machine_w ?? row.tpmPerMachine),
    totalCapacity: Number(cluster.total_capacity_w ?? row.totalCapacity),
    realtimeRuntimeTpm: Number(cluster.current_tpm_w ?? row.realtimeRuntimeTpm ?? row.runtimeTpm),
    idleRuntimeTpm: Number(cluster.peak_tpm_idle !== undefined ? toWanTpm(cluster.peak_tpm_idle) : row.idleRuntimeTpm ?? row.runtimeTpm),
    busyRuntimeTpm: Number(cluster.peak_tpm_busy !== undefined ? toWanTpm(cluster.peak_tpm_busy) : row.busyRuntimeTpm ?? row.runtimeTpm),
    runtimeTpm: Number(cluster.current_tpm_w ?? row.runtimeTpm),
    redundantTpm: Number(cluster.current_redundant_w ?? row.redundantTpm),
    redundantMachines: Number(cluster.current_redundant_machines ?? row.redundantMachines),
    clusterUtilization: Number(cluster.cluster_utilization ?? row.clusterUtilization),
  };
  return normalizeClusterRow(nextRow);
}

function chartMax(data: Array<Record<string, number | string>>, lines: ChartLine[]) {
  return Math.max(...lines.flatMap((line) => data.map((point) => Number(point[line.key] || 0))), 1);
}

function chartDomain(data: Array<Record<string, number | string>>, lines: ChartLine[]): [number, number] {
  const max = chartMax(data, lines);
  return [0, Math.ceil(max * 1.2)];
}

function chartTicks(data: Array<Record<string, number | string>>, lines: ChartLine[]) {
  const max = chartDomain(data, lines)[1];
  return Array.from({ length: 5 }, (_, index) => Math.round((max / 4) * index));
}

function buildSummary(data: Array<Record<string, number | string>>, lines: ChartLine[], formatter: (value: number) => string): ChartSummaryRow[] {
  return lines.map((line) => {
    const values = data.map((point) => Number(point[line.key] || 0));
    const max = values.length ? Math.max(...values) : 0;
    const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
    const last = values[values.length - 1] || 0;
    return { label: line.name, color: line.color, max: formatter(max), mean: formatter(mean), last: formatter(last) };
  });
}

function buildModelRuntime(items: ConsumerTpmSnapshot[]) {
  const models = Array.from(new Set(items.map((item) => item.ai_model))).slice(0, 6);
  const lines = models.map((model, index) => ({ key: `model${index}`, name: model, color: chartColors[index % chartColors.length] }));
  const byTime = new Map<string, Record<string, number | string>>();
  items.forEach((item) => {
    const modelIndex = models.indexOf(item.ai_model);
    if (modelIndex < 0) return;
    const time = timeLabel(item.data_time);
    const row = byTime.get(time) || { time };
    const key = `model${modelIndex}`;
    row[key] = Number(row[key] || 0) + Number(item.tpm || 0);
    byTime.set(time, row);
  });
  const data = Array.from(byTime.values());
  return { data, lines, yDomain: chartDomain(data, lines), yTicks: chartTicks(data, lines), summary: buildSummary(data, lines, formatTpm) };
}

function buildShareRuntime(items: ConsumerTpmSnapshot[]) {
  const models = Array.from(new Set(items.map((item) => item.ai_model))).slice(0, 6);
  const lines = models.map((model, index) => ({ key: `share${index}`, name: `${model} 自建`, color: chartColors[index % chartColors.length] }));
  const buckets = new Map<string, { row: Record<string, number | string>; count: Record<string, number> }>();
  items.forEach((item) => {
    const modelIndex = models.indexOf(item.ai_model);
    if (modelIndex < 0 || item.self_ratio === null || item.self_ratio === undefined) return;
    const time = timeLabel(item.data_time);
    const bucket = buckets.get(time) || { row: { time }, count: {} };
    const key = `share${modelIndex}`;
    bucket.row[key] = Number(bucket.row[key] || 0) + Number(item.self_ratio || 0) * 100;
    bucket.count[key] = (bucket.count[key] || 0) + 1;
    buckets.set(time, bucket);
  });
  const data = Array.from(buckets.values()).map((bucket) => {
    lines.forEach((line) => {
      if (bucket.count[line.key]) bucket.row[line.key] = Number(bucket.row[line.key] || 0) / bucket.count[line.key];
    });
    return bucket.row;
  });
  return { data, lines, summary: buildSummary(data, lines, formatPercentAxis) };
}

function hasVisibleFittingSeries(result: FittingResult) {
  return (result.series_json || []).some(([, value]) => Number.isFinite(Number(value)) && Math.abs(Number(value)) > 0);
}

function sortLatestFittingResults(results: FittingResult[]) {
  return [...results].sort((a, b) => String(b.generated_at || '').localeCompare(String(a.generated_at || '')));
}

function buildFittingChart(results: FittingResult[]) {
  // 结果按 generated_at 倒序，按集群去重取首条（即最新批次），避免多次跑拟合产生重复线；
  // 空序列/全 0 序列不生成 legend，避免 legend 有项但图中没有可见曲线。
  const byCluster = new Map<string, FittingResult>();
  sortLatestFittingResults(results).forEach((item) => {
    const key = item.cluster_name || item.ai_consumer || item.model_name;
    if (key && hasVisibleFittingSeries(item) && !byCluster.has(key)) byCluster.set(key, item);
  });
  const selected = Array.from(byCluster.values());
  const lines = selected.map((item, index) => ({
    key: `fit${index}`,
    name: item.cluster_name || item.ai_consumer || item.model_name,
    color: chartColors[index % chartColors.length],
    strokeDasharray: index === 2 ? '5 5' : undefined,
  }));
  // 按时间标签合并：并集所有集群的时间戳，缺值补 0，保证各线 X 轴对齐、不丢时段
  // （旧版按 pointIndex 对齐，集群点数不一致时会错位丢点，如忙时 Kimi-K2.6 仅 1 点）。
  const byTime = new Map<string, Record<string, number | string>>();
  // 每个集群各整点拟合值（用于"当前小时"取数）：lineKey -> { 'HH:00': tpm }
  const hourlyByLine: Record<string, Record<string, number>> = {};
  selected.forEach((result, resultIndex) => {
    const key = `fit${resultIndex}`;
    hourlyByLine[key] = {};
    (result.series_json || []).forEach(([ts, value]) => {
      const time = timeLabel(ts);
      const row = byTime.get(time) || { time };
      row[key] = Number(value || 0);
      byTime.set(time, row);
      hourlyByLine[key][time] = Number(value || 0);
    });
  });
  const rows = Array.from(byTime.values()).sort((a, b) => String(a.time).localeCompare(String(b.time)));
  return { data: rows, lines, yDomain: chartDomain(rows, lines), yTicks: chartTicks(rows, lines), hourlyByLine };
}

function buildCustomerFitWaves(results: FittingResult[], ratios: ConsumerTpmSnapshot[]): CustomerFitWave[] {
  const byModel = new Map<string, FittingResult[]>();
  sortLatestFittingResults(results).forEach((result) => {
    if (!hasVisibleFittingSeries(result)) return;
    const items = byModel.get(result.model_name) || [];
    items.push(result);
    byModel.set(result.model_name, items);
  });
  return Array.from(byModel.entries()).map(([model, modelResults]) => {
    // 不再 slice(0,6)：展示该模型下全部有有效拟合序列的客户；同一客户只取最新一条。
    const byCustomer = new Map<string, FittingResult>();
    modelResults.forEach((result) => {
      const key = result.ai_consumer || result.cluster_name || result.model_name;
      if (key && !byCustomer.has(key)) byCustomer.set(key, result);
    });
    const selected = Array.from(byCustomer.values());
    const lines = selected.map((result, index) => ({
      key: `customer${index}`,
      name: result.ai_consumer || result.cluster_name || result.model_name,
      color: chartColors[index % chartColors.length],
      strokeDasharray: index === 2 ? '5 5' : undefined,
    }));
    // 按时间标签合并：并集各客户时间戳、缺值补 0，保证各线 X 轴对齐、不丢时段
    // （旧版按 pointIndex 对齐，客户点数不一致时会错位）。
    const byTime = new Map<string, Record<string, number | string>>();
    selected.forEach((result, resultIndex) => {
      const key = `customer${resultIndex}`;
      (result.series_json || []).forEach(([ts, value]) => {
        const time = timeLabel(ts);
        const row = byTime.get(time) || { time };
        row[key] = Number(value || 0);
        byTime.set(time, row);
      });
    });
    const data = Array.from(byTime.values()).sort((a, b) => String(a.time).localeCompare(String(b.time)));
    const dispatchRatios = selected.map((result, index) => {
      const current = ratios.find((item) => item.ai_model === result.model_name && item.ai_consumer === result.ai_consumer);
      const selfRatio = Number(current?.self_ratio || 0);
      const vendorRatio = Number(current?.thirdparty_ratio ?? Math.max(1 - selfRatio, 0));
      return { key: `customer${index}`, name: result.ai_consumer || result.cluster_name || result.model_name, color: chartColors[index % chartColors.length], selfRatio, vendorRatio };
    });
    return { model, data, lines, ratios: dispatchRatios, yDomain: chartDomain(data, lines), yTicks: chartTicks(data, lines) };
  });
}

function emptyCustomerFitWave(): CustomerFitWave {
  return { model: '-', data: [], lines: [], ratios: [], yDomain: [0, 1], yTicks: [0, 1] };
}


function formatTpm(value: number) {
  if (value >= 1000000) return `${Number((value / 1000000).toFixed(1))} Mil`;
  if (value >= 1000) return `${Number((value / 1000).toFixed(0))} K`;
  return String(value);
}

// 拟合波形按原始 TPM 入图，展示时换算为 Mil(百万TPM)。
function formatTpmMillionsAxis(value: number) {
  return (value / 1000000).toFixed(1);
}

function formatTpmMillionsTip(value: number) {
  return `${(value / 1000000).toFixed(1)} Mil`;
}

function formatPercentAxis(value: number) {
  return `${value.toFixed(2)}%`;
}


function toWanTpm(value?: number | null) {
  return Number(((Number(value || 0)) / 10000).toFixed(2));
}

function formatDiscount(value?: number | null) {
  const n = Number(value || 0);
  return n > 0 ? percent(n) : '-';
}

function rawJsonValue(row: VendorQuota, key: string) {
  const value = row.raw_json?.[key];
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function normalizeModelName(value: string) {
  return value.trim().toLowerCase();
}

function buildVendorModelGroups(rows: VendorRuntimeRow[]): VendorModelGroup[] {
  return Array.from(new Set(rows.map((row) => normalizeModelName(row.modelName)))).map((modelName) => {
    const groupRows = rows.filter((row) => normalizeModelName(row.modelName) === modelName);
    const quotaW = groupRows.reduce((total, row) => total + row.quotaW, 0);

    const onlineRuntime = groupRows.reduce((total, row) => total + row.onlineRuntime, 0);
    const redundantRuntime = groupRows.reduce((total, row) => total + row.redundantRuntime, 0);
    return {
      modelName,
      rows: groupRows,
      quotaW,
      onlineRuntime,
      redundantRuntime,
      runtimeRatio: quotaW > 0 ? onlineRuntime / quotaW : 0,
    };
  });
}

function getLineMax(data: Array<Record<string, number | string>>, key: string) {
  return data.reduce((max, point) => Math.max(max, Number(point[key] || 0)), 0);
}

function getCustomerWatermarks(wave: CustomerFitWave): CustomerWatermark[] {
  return wave.ratios.map((item) => {
    const peakDemand = getLineMax(wave.data, item.key);
    return {
      key: item.key,
      name: item.name,
      color: item.color,
      peakDemand,
      selfWatermark: Math.round(peakDemand * item.selfRatio),
      vendorTakeover: Math.round(peakDemand * item.vendorRatio),

    };
  });
}

function mapVendorQuota(row: VendorQuota): VendorRuntimeRow {
  const quotaW = toWanTpm(row.quota_tpm);

  const onlineRuntime = toWanTpm(row.actual_tpm);
  const redundantRuntime = Math.max(toWanTpm(row.actual_redundant_tpm), 0);
  return {
    id: String(row.id),
    vendorName: row.vendor,
    providerName: rawJsonValue(row, 'provider'),
    modelName: normalizeModelName(row.model),

    quotaW,
    purchaseDiscount: Number(row.purchase_discount || 0),
    purchaseDiscountText: formatDiscount(row.purchase_discount),

    onlineRuntime,
    redundantRuntime,
    runtimeRatio: quotaW > 0 ? onlineRuntime / quotaW : 0,
  };
}

function buildVendorMetrics(rows: VendorRuntimeRow[]): MetricItem[] {
  const quotaW = rows.reduce((total, row) => total + row.quotaW, 0);
  const onlineRuntime = rows.reduce((total, row) => total + row.onlineRuntime, 0);
  const redundantRuntime = rows.reduce((total, row) => total + row.redundantRuntime, 0);
  const runtimeRatio = quotaW > 0 ? onlineRuntime / quotaW : 0;
  return [
    { label: '模型维度供应商总量', value: numberText(quotaW) },
    { label: '实际占用总量', value: numberText(onlineRuntime) },
    { label: '实际占用百分比', value: percent(runtimeRatio) },
    { label: '冗余量', value: numberText(redundantRuntime) },
  ];
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

function CapacityBarShape({ x = 0, y = 0, width = 0, height = 0, payload }: CapacityBarShapeProps) {
  const utilization = Math.max(0, Math.min(1, payload?.clusterUtilization || 0));
  const runtimeHeight = height * utilization;
  const runtimeY = y + height - runtimeHeight;
  const lineY = runtimeY;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={7} fill="rgba(39, 215, 255, .18)" />
      {runtimeHeight > 0 ? <rect x={x} y={runtimeY} width={width} height={runtimeHeight} rx={7} fill="rgba(93, 255, 178, .42)" /> : null}
      <line x1={x - 4} x2={x + width + 4} y1={lineY} y2={lineY} stroke="#f5d54b" strokeWidth={2.5} />
      <text x={x + width / 2} y={Math.max(y - 8, 12)} textAnchor="middle" fill="#bdefff" fontSize="11" fontWeight={700}>
        {numberText(payload?.totalCapacity || 0)}
      </text>
    </g>
  );
}

function RuntimeLineChart({ title, data, lines, summary, yDomain, yTicks, yFormatter, tooltipFormatter, tooltipSingleKey, selectedLineKey, hoveredLineKey, legendRenderer, referenceLines, onLineClick, forceSolidLines }: RuntimeLineChartProps) {
  // 选中或悬停的线优先高亮，其余变暗；悬停优先级高于选中。
  const focusKey = hoveredLineKey ?? selectedLineKey ?? null;
  const pointCountByLine = new Map(lines.map((line) => [
    line.key,
    data.reduce((count, point) => (point[line.key] == null ? count : count + 1), 0),
  ]));
  // tooltip 只显示单条线时，预解析该线的名称/颜色。
  const singleLine = tooltipSingleKey ? lines.find((l) => l.key === tooltipSingleKey) : null;
  return (
    <div className="realtime-chart-card">
      <div className="realtime-chart-title">{title}</div>
      <div className="realtime-chart-canvas">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -2 }}>
            <CartesianGrid stroke="rgba(82, 191, 255, .12)" strokeDasharray="3 3" />
            <XAxis dataKey="time" axisLine={false} tickLine={false} minTickGap={12} interval={data.length <= 12 ? 0 : 'preserveStartEnd'} tick={{ fill: '#7898a7', fontSize: 11 }} />
            <YAxis width={44} domain={yDomain} ticks={yTicks} tickFormatter={(value) => yFormatter(Number(value))} axisLine={false} tickLine={false} tick={{ fill: '#7898a7', fontSize: 11 }} />
            <Tooltip
              contentStyle={{ background: '#071018', border: '1px solid rgba(82, 191, 255, .28)', borderRadius: 8 }}
              labelStyle={{ color: '#e6f7ff' }}
              formatter={tooltipFormatter ? (value) => tooltipFormatter(Number(value)) : undefined}
              // 选中某集群后悬浮只显示该集群：按 tooltipSingleKey 过滤掉其余线。
              itemSorter={(item) => (tooltipSingleKey && item.dataKey === tooltipSingleKey ? -1 : 1)}
              wrapperStyle={tooltipSingleKey ? { visibility: 'visible' } : undefined}
              // 自定义渲染：只保留 tooltipSingleKey 对应的一条。
              content={tooltipSingleKey && singleLine ? (props) => {
                const { label, payload } = props as { label?: string; payload?: Array<{ dataKey?: string; value?: number | string }> };
                const hit = payload?.find((p) => p.dataKey === tooltipSingleKey);
                if (!hit || hit.value == null || !Number.isFinite(Number(hit.value))) return null;
                const raw = Number(hit.value);
                const text = tooltipFormatter ? tooltipFormatter(raw) : String(raw);
                return (
                  <div style={{ background: '#071018', border: '1px solid rgba(82, 191, 255, .28)', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>

                    <div style={{ color: '#e6f7ff', marginBottom: 2 }}>{label}</div>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#b8d5e0' }}>
                      <i style={{ width: 12, height: 3, borderRadius: 999, background: singleLine.color, display: 'inline-block' }} />
                      {singleLine.name}: <strong style={{ color: singleLine.color }}>{text}</strong>
                    </div>
                  </div>
                );
              } : undefined}
            />
            {referenceLines?.map((line) => (
              <ReferenceLine key={line.key} y={line.value} stroke={line.color} strokeDasharray={line.strokeDasharray || '6 6'} strokeOpacity={0.45} strokeWidth={2} ifOverflow="extendDomain" />
            ))}
            {lines.map((line) => {
              const isSelected = selectedLineKey === line.key;
              const isHovered = hoveredLineKey === line.key;
              const isDimmed = Boolean(focusKey && focusKey !== line.key);
              const shouldShowDot = Number(pointCountByLine.get(line.key) || 0) < 2;
              return (
                <Line
                  key={line.key}
                  type="monotone"
                  dataKey={line.key}
                  name={line.name}
                  stroke={line.color}
                  strokeWidth={isSelected || isHovered ? 2.6 : 2}
                  strokeDasharray={forceSolidLines ? undefined : line.strokeDasharray}
                  strokeOpacity={isDimmed ? 0.28 : 1}

                  dot={shouldShowDot ? { r: 3, strokeWidth: 0 } : false}
                  activeDot={onLineClick ? { r: 4, onClick: () => onLineClick(line.key) } : false}
                  isAnimationActive={false}
                  onClick={onLineClick ? () => onLineClick(line.key) : undefined}
                  style={onLineClick ? { cursor: 'pointer' } : undefined}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {legendRenderer ? legendRenderer() : summary ? (

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
      ) : (
        <div className="fit-wave-legend">
          {lines.map((line) => <span key={line.key}><i style={{ backgroundColor: line.color }} />{line.name}</span>)}
        </div>
      )}
    </div>
  );
}

export function RealtimeDashboard() {
  const [selfHostedRows, setSelfHostedRows] = useState<SelfHostedClusterRow[]>([]);
  const [vendorRows, setVendorRows] = useState<VendorRuntimeRow[]>([]);
  const [consumerSnapshots, setConsumerSnapshots] = useState<ConsumerTpmSnapshot[]>([]);
  const [consumerTpmOptions, setConsumerTpmOptions] = useState<ConsumerTpmFilterOptions>(emptyConsumerTpmOptions);
  const [consumerTpmDraftFilters, setConsumerTpmDraftFilters] = useState<ConsumerTpmFilters>({ range: defaultConsumerTpmRange() });
  const [consumerTpmQueryFilters, setConsumerTpmQueryFilters] = useState<ConsumerTpmFilters>({ range: defaultConsumerTpmRange() });
  const [idleClusterFits, setIdleClusterFits] = useState<FittingResult[]>([]);
  const [busyClusterFits, setBusyClusterFits] = useState<FittingResult[]>([]);
  const [idleCustomerFits, setIdleCustomerFits] = useState<FittingResult[]>([]);
  const [busyCustomerFits, setBusyCustomerFits] = useState<FittingResult[]>([]);
  const [savingClusterId, setSavingClusterId] = useState<string | null>(null);
  const [editingClusterId, setEditingClusterId] = useState<string | null>(null);
  const [editingTpmValue, setEditingTpmValue] = useState<number | null>(null);
  const [selectedFitModel, setSelectedFitModel] = useState('');

  const [selectedCustomerKey, setSelectedCustomerKey] = useState<string | null>(null);
  const [hoveredClusterFitKey, setHoveredClusterFitKey] = useState<string | null>(null);

  const vendorMetrics = useMemo(() => buildVendorMetrics(vendorRows), [vendorRows]);
  const modelRuntime = useMemo(() => buildModelRuntime(consumerSnapshots), [consumerSnapshots]);
  const shareRuntime = useMemo(() => buildShareRuntime(consumerSnapshots), [consumerSnapshots]);
  const idleClusterFit = useMemo(() => buildFittingChart(idleClusterFits), [idleClusterFits]);
  const busyClusterFit = useMemo(() => buildFittingChart(busyClusterFits), [busyClusterFits]);
  const idleCustomerFitWaves = useMemo(() => buildCustomerFitWaves(idleCustomerFits, consumerSnapshots), [idleCustomerFits, consumerSnapshots]);
  const busyCustomerFitWaves = useMemo(() => buildCustomerFitWaves(busyCustomerFits, consumerSnapshots), [busyCustomerFits, consumerSnapshots]);

  const applyConsumerTpmFilters = () => {
    setConsumerTpmQueryFilters({
      ...consumerTpmDraftFilters,
      range: consumerTpmDraftFilters.range ? [...consumerTpmDraftFilters.range] as [Dayjs, Dayjs] : null,
    });
  };

  const resetConsumerTpmFilters = () => {
    const range = defaultConsumerTpmRange();
    const nextFilters: ConsumerTpmFilters = { range };
    setConsumerTpmDraftFilters(nextFilters);
    setConsumerTpmQueryFilters(nextFilters);
  };

  useEffect(() => {
    let cancelled = false;
    const watchedNamesPromise = watchedClustersApi.list().then(watchedClusterNames);
    watchedNamesPromise.then((watchedNames) => dashboardsApi.resources({}).then((data) => ({ data, watchedNames }))).then(({ data, watchedNames }) => {
      if (cancelled) return;
      setSelfHostedRows((data.clusters || []).filter((cluster) => isWatchedCluster(cluster.cluster_name, watchedNames)).map(mapResourceCluster));
    }).catch(() => undefined);

    vendorsApi.quotas({ status: 'active', page_size: 100 }).then((data) => {

      if (cancelled) return;
      setVendorRows(data.items.map(mapVendorQuota));
    }).catch(() => undefined);
    monitorApi.consumerTpmOptions().then((data) => {
      if (cancelled) return;
      setConsumerTpmOptions({
        aiModels: data.ai_models || [],
        aiConsumers: data.ai_consumers || [],
        customerCodes: data.customer_codes || [],
      });
    }).catch(() => undefined);
    watchedNamesPromise.then((names) => fittingsApi.results({ level: 'cluster', period: 'idle', page_size: 100 }).then((data) => ({ data, names }))).then(({ data, names }) => {
      if (cancelled) return;
      setIdleClusterFits((data.items || []).filter((item) => isWatchedCluster(item.cluster_name, names)));
    }).catch(() => undefined);
    watchedNamesPromise.then((names) => fittingsApi.results({ level: 'cluster', period: 'busy', page_size: 100 }).then((data) => ({ data, names }))).then(({ data, names }) => {
      if (cancelled) return;
      setBusyClusterFits((data.items || []).filter((item) => isWatchedCluster(item.cluster_name, names)));
    }).catch(() => undefined);


    fittingsApi.results({ level: 'customer', period: 'idle', page_size: 100 }).then((data) => {
      if (cancelled) return;
      setIdleCustomerFits(data.items || []);
    }).catch(() => undefined);
    fittingsApi.results({ level: 'customer', period: 'busy', page_size: 100 }).then((data) => {
      if (cancelled) return;
      setBusyCustomerFits(data.items || []);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const [start, end] = consumerTpmQueryFilters.range || [];
    monitorApi.consumerTpm({
      ai_consumer: consumerTpmQueryFilters.aiConsumer,
      ai_model: consumerTpmQueryFilters.aiModel,
      customer_code: consumerTpmQueryFilters.customerCode,
      start_time: start?.format('YYYY-MM-DDTHH:mm:ss'),
      end_time: end?.format('YYYY-MM-DDTHH:mm:ss'),
    }).then((data) => {
      if (cancelled) return;
      setConsumerSnapshots(data.items || []);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [consumerTpmQueryFilters]);

  useEffect(() => {
    const nextModel = idleCustomerFitWaves[0]?.model || busyCustomerFitWaves[0]?.model || '';
    if (!selectedFitModel && nextModel) setSelectedFitModel(nextModel);
  }, [idleCustomerFitWaves, busyCustomerFitWaves, selectedFitModel]);


  const saveTpmPerMachine = async (record: SelfHostedClusterRow, value: number | null) => {
    const nextValue = Number(value || 0);
    if (nextValue === record.tpmPerMachine) {
      setEditingClusterId(null);
      setEditingTpmValue(null);
      return;
    }
    setSavingClusterId(record.id);
    try {

      const updatedCluster = await dashboardsApi.updateClusterResource({
        cluster_name: record.clusterName,
        deployed_model: record.deployedModel,
        provider: record.provider,
        machine_count: record.machineCount,
        tpm_per_machine_w: nextValue,
        current_tpm_w: record.realtimeRuntimeTpm ?? record.runtimeTpm,
      });
      setSelfHostedRows((rows) => rows.map((row) => (row.id === record.id ? mergeClusterResponse(row, updatedCluster) : row)));
      setEditingClusterId(null);
      setEditingTpmValue(null);
      message.success('单机承载能力已保存');

    } catch (error) {
      message.error(error instanceof Error ? error.message : '单机承载能力保存失败');
    } finally {
      setSavingClusterId(null);
    }
  };

  const renderTpmInput = (record: SelfHostedClusterRow) => {
    const editing = editingClusterId === record.id;
    if (!editing) {
      return (
        <button
          type="button"
          className="cluster-tpm-value-button"
          disabled={savingClusterId === record.id}
          onClick={() => {
            setEditingClusterId(record.id);
            setEditingTpmValue(Number(record.tpmPerMachine || 0));
          }}
        >
          {numberText(record.tpmPerMachine)}
        </button>
      );
    }
    return (
      <div className="cluster-tpm-editor">
        <InputNumber
          className="realtime-cell-number"
          min={0}
          size="small"
          value={editingTpmValue ?? 0}
          disabled={savingClusterId === record.id}
          autoFocus
          onChange={(value) => setEditingTpmValue(Number(value || 0))}
          onPressEnter={() => saveTpmPerMachine(record, editingTpmValue)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setEditingClusterId(null);
              setEditingTpmValue(null);
            }
          }}
        />
        <Button
          className="cluster-tpm-confirm"
          type="text"
          size="small"
          icon={<CheckOutlined />}
          loading={savingClusterId === record.id}
          onClick={() => saveTpmPerMachine(record, editingTpmValue)}
        />
      </div>
    );
  };


  const renderSelfHostedClusterChart = (period: ResourcePeriod) => {
    const chartRows = buildClusterRows(selfHostedRows, period).filter((row) => row.id !== 'total');
    return (
      <>
        <div className="cluster-capacity-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartRows} margin={{ top: 28, right: 18, bottom: 64, left: 2 }} barCategoryGap="22%">
              <CartesianGrid stroke="rgba(82, 191, 255, .12)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="clusterName" interval={0} angle={-32} textAnchor="end" height={76} tick={{ fill: '#9ec7d8', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(value) => numberText(Number(value))} tick={{ fill: '#7898a7', fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
              <Tooltip
                cursor={{ fill: 'rgba(39, 215, 255, .08)' }}
                contentStyle={{ background: '#071018', border: '1px solid rgba(82, 191, 255, .28)', borderRadius: 8 }}
                formatter={(_, name, item) => {
                  const row = item.payload as SelfHostedClusterRow;
                  if (name === 'totalCapacity') return [`总承载能力 ${numberText(row.totalCapacity)}，冗余TPM ${numberText(row.redundantTpm)}`, '承载能力'];
                  return [String(_), String(name)];
                }}
                labelFormatter={(label, items) => {
                  const row = items[0]?.payload as SelfHostedClusterRow | undefined;
                  return row ? `${label} | ${row.machineCount}台 | 利用率 ${percent(row.clusterUtilization)}` : String(label);
                }}
              />
              <Bar dataKey="totalCapacity" shape={<CapacityBarShape />} isAnimationActive={false}>
                {chartRows.map((row) => <Cell key={row.id} fill={row.totalCapacity > 0 ? '#27d7ff' : 'rgba(82, 191, 255, .15)'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="cluster-chart-legend">
          <span><i className="legend-capacity" />总承载能力</span>
          <span><i className="legend-runtime" />实跑TPM位置/集群利用率</span>
          <span><i className="legend-redundant" />冗余TPM</span>
        </div>
        <div className="cluster-tpm-editor-grid">
          {chartRows.map((row) => (
            <div className="cluster-tpm-editor" key={row.id}>
              <span title={row.clusterName}>{row.clusterName}</span>
              <strong>{row.machineCount}台</strong>
              {renderTpmInput(row)}
            </div>
          ))}
        </div>
      </>
    );
  };

  const renderSelfHostedCluster = (period: ResourcePeriod) => (
    <section className="wire-card realtime-panel realtime-cluster-panel">
      <div className="wire-card-title">自建集群</div>
      <MetricStrip items={buildSelfHostedMetrics(selfHostedRows, period)} />
      {renderSelfHostedClusterChart(period)}
    </section>
  );

  const renderVendorRuntime = () => {
    const modelGroups = buildVendorModelGroups(vendorRows);
    const maxQuotaW = Math.max(...vendorRows.map((row) => row.quotaW), 1);

    return (
      <section className="wire-card realtime-panel realtime-vendor-panel">

        <div className="wire-card-title">三方供应商</div>
        <MetricStrip items={vendorMetrics} />
        <div className="vendor-runtime-chart" role="img" aria-label="三方供应商按模型展示供应量级和当前实跑占比">
          {modelGroups.map((group) => (
            <div className="vendor-model-group" key={group.modelName} title={`${group.modelName} | 供应商总量 ${numberText(group.quotaW)} 万TPM | 实际占用 ${numberText(group.onlineRuntime)} 万TPM | 冗余 ${numberText(group.redundantRuntime)} 万TPM | 占比 ${percent(group.runtimeRatio)}`}>
              <div className="vendor-model-name">{group.modelName}</div>
              <div className="vendor-model-stats">
                <span><b>总量</b>{numberText(group.quotaW)}</span>
                <span><b>占用</b>{numberText(group.onlineRuntime)}</span>
                <span><b>占比</b>{percent(group.runtimeRatio)}</span>
                <span><b>冗余</b>{numberText(group.redundantRuntime)}</span>
              </div>
              <div className="vendor-bar-stage">
                {group.rows.map((row) => {
                  const quotaHeight = Math.max((row.quotaW / maxQuotaW) * 100, row.quotaW > 0 ? 8 : 0);
                  const runtimePercent = Math.max(Math.min(row.runtimeRatio * 100, 100), 0);
                  const vendorLabel = row.providerName ? `${row.vendorName} ${row.providerName}` : row.vendorName;
                  return (
                    <div className="vendor-bar-cell" key={row.id} title={`${vendorLabel} | 供应总量 ${numberText(row.quotaW)} 万TPM | 当前实跑 ${numberText(row.onlineRuntime)} 万TPM | 冗余 ${numberText(row.redundantRuntime)} 万TPM | 占比 ${percent(row.runtimeRatio)} | 折扣 ${row.purchaseDiscountText}`}>
                      <div className="vendor-bar-label">{numberText(row.quotaW)}w</div>
                      <div className="vendor-bar" style={{ height: `${quotaHeight}%` }}>
                        <span className="vendor-bar-line" style={{ bottom: `${runtimePercent}%` }} />
                      </div>
                      <div className="vendor-supplier-axis" title={vendorLabel}>{row.vendorName}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="cluster-chart-legend vendor-chart-legend">

          <span><i className="legend-capacity" />供应量级</span>
          <span><i className="legend-runtime" />当前实跑量级位置/占比</span>
          <span><i className="legend-redundant" />可用冗余量</span>
        </div>
      </section>
    );
  };

  const renderCustomerModelRuntime = () => (
    <section className="wire-card realtime-panel realtime-runtime-panel">
      <div className="wire-card-title">客户模型跑量图</div>
      <Form layout="inline" className="realtime-filter-grid">
        <Form.Item label="时间范围">
          <DatePicker.RangePicker
            showTime
            value={consumerTpmDraftFilters.range}
            onChange={(range) => setConsumerTpmDraftFilters((current) => ({ ...current, range: range as [Dayjs, Dayjs] | null }))}
          />
        </Form.Item>
        <Form.Item label="模型">
          <Select
            allowClear
            showSearch
            placeholder="全部"
            value={consumerTpmDraftFilters.aiModel}
            options={selectOptions(consumerTpmOptions.aiModels)}
            onChange={(value) => setConsumerTpmDraftFilters((current) => ({ ...current, aiModel: value }))}
            style={{ minWidth: 180 }}
          />
        </Form.Item>
        <Form.Item label="客户">
          <Select
            allowClear
            showSearch
            placeholder="全部"
            value={consumerTpmDraftFilters.aiConsumer}
            options={selectOptions(consumerTpmOptions.aiConsumers)}
            onChange={(value) => setConsumerTpmDraftFilters((current) => ({ ...current, aiConsumer: value }))}
            style={{ minWidth: 180 }}
          />
        </Form.Item>
        <Form.Item label="用户ID">
          <Select
            allowClear
            showSearch
            placeholder="全部"
            value={consumerTpmDraftFilters.customerCode}
            options={selectOptions(consumerTpmOptions.customerCodes)}
            onChange={(value) => setConsumerTpmDraftFilters((current) => ({ ...current, customerCode: value }))}
            style={{ minWidth: 180 }}
          />
        </Form.Item>
        <div className="realtime-filter-actions">
          <Button type="primary" htmlType="button" icon={<SearchOutlined />} onClick={applyConsumerTpmFilters}>查询</Button>
          <Button htmlType="button" icon={<ReloadOutlined />} onClick={resetConsumerTpmFilters}>重置</Button>
        </div>
      </Form>
      <div className="realtime-chart-stack">
        <RuntimeLineChart
          title="售卖模型TPM(BODHIMIND SDN.BHD.)"
          data={modelRuntime.data}
          lines={modelRuntime.lines}
          yDomain={modelRuntime.yDomain}
          yTicks={modelRuntime.yTicks}
          yFormatter={formatTpm}
          summary={modelRuntime.summary}
        />
        <RuntimeLineChart
          title="售卖模型分发后端TPM占比(自建第三方维度，BODHIMIND SDN.BHD.)"
          data={shareRuntime.data}
          lines={shareRuntime.lines}
          yDomain={[0, 200]}
          yTicks={[0, 50, 100, 150, 200]}
          yFormatter={formatPercentAxis}
          summary={shareRuntime.summary}
        />
        <RuntimeLineChart
          title="售卖模型分发后端TPM占比(模型维度，BODHIMIND SDN.BHD.)"
          data={shareRuntime.data}
          lines={shareRuntime.lines}
          yDomain={[0, 200]}
          yTicks={[0, 50, 100, 150, 200]}
          yFormatter={formatPercentAxis}
          summary={shareRuntime.summary}
        />

      </div>
    </section>
  );

  const renderCustomerDispatchRatios = (wave: CustomerFitWave) => {
    const watermarks = getCustomerWatermarks(wave);
    const activeKey = watermarks.some((item) => item.key === selectedCustomerKey) ? selectedCustomerKey : null;
    return (
      <div className="customer-watermark-grid">
        {watermarks.map((item) => {
          const isSelected = item.key === activeKey;

          return (
            <button
              type="button"
              className={`customer-watermark-item${isSelected ? ' is-selected' : ''}`}
              key={item.key}
              title={`${item.name} | 跑量峰值 ${numberText(item.peakDemand)} TPM | 自建水位线 ${numberText(item.selfWatermark)} TPM | 三方承接 ${numberText(item.vendorTakeover)} TPM`}
              onClick={() => setSelectedCustomerKey((current) => (current === item.key ? null : item.key))}
            >
              <span className="customer-watermark-name"><i style={{ backgroundColor: item.color }} />{item.name}</span>
              {isSelected ? (
                <span className="customer-watermark-values">
                  <span><b>实际/拟合跑量</b>{numberText(item.peakDemand)}</span>
                  <span><b>自建水位线</b>{numberText(item.selfWatermark)}</span>
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    );
  };


  const renderFitRuntime = (period: Extract<ResourcePeriod, 'idle' | 'busy'>) => {

    const isBusy = period === 'busy';
    const clusterFit = isBusy ? busyClusterFit : idleClusterFit;
    const customerWaves = isBusy ? busyCustomerFitWaves : idleCustomerFitWaves;
    const selectedCustomerFitWave = customerWaves.find((item) => item.model === selectedFitModel) || customerWaves[0] || emptyCustomerFitWave();
    const watermarks = getCustomerWatermarks(selectedCustomerFitWave);

    const selectedWatermark = watermarks.find((item) => item.key === selectedCustomerKey) || null;
    const activeCustomerKey = selectedWatermark?.key || null;

    // 取某集群在「当前小时」的拟合值：当前整点命中序列则直接取；否则取序列中与当前小时
    // 距离最近的一点的值（如闲时序列 0-8 点、当前 14 点时回退到最近的 08:00）。
    const currentHour = dayjs().format('HH:00');
    const currentHourValue = (lineKey: string): number | null => {
      const hourly = clusterFit.hourlyByLine?.[lineKey];
      if (!hourly) return null;
      if (hourly[currentHour] != null) return hourly[currentHour];
      const times = Object.keys(hourly).sort();
      if (!times.length) return null;
      const idx = times.reduce((best, t, i) => (Math.abs(Number(t.slice(0, 2)) - Number(currentHour.slice(0, 2))) < Math.abs(Number(times[best].slice(0, 2)) - Number(currentHour.slice(0, 2))) ? i : best), 0);
      return hourly[times[idx]];
    };

    return (
      <div className="idle-fit-module-stack">
        <section className="wire-card realtime-panel realtime-runtime-panel idle-fit-panel">

          <div className="wire-card-title">集群拟合波形</div>
          <RuntimeLineChart
            title={isBusy ? '忙时跑量预估（Mil，08:00-24:00）' : '闲时跑量预估（Mil）'}
            data={clusterFit.data}
            lines={clusterFit.lines}
            yDomain={clusterFit.yDomain}
            yTicks={clusterFit.yTicks}
            yFormatter={formatTpmMillionsAxis}
            tooltipFormatter={formatTpmMillionsTip}
            tooltipSingleKey={hoveredClusterFitKey}
            hoveredLineKey={hoveredClusterFitKey}
            onLineClick={(key) => setHoveredClusterFitKey((current) => (current === key ? null : key))}
            legendRenderer={() => (
              <div className="fit-cluster-legend">
                <span className="fit-cluster-legend-hint">当前 {currentHour} · 选中集群后，悬浮折线只显示该集群的拟合值</span>
                {clusterFit.lines.map((line) => {
                  const val = currentHourValue(line.key);
                  const isHovered = hoveredClusterFitKey === line.key;
                  return (
                    <span
                      key={line.key}
                      className={`fit-cluster-legend-item${isHovered ? ' is-active' : ''}`}
                      onMouseEnter={() => setHoveredClusterFitKey(line.key)}
                      onMouseLeave={() => setHoveredClusterFitKey(null)}
                      onClick={() => setHoveredClusterFitKey((current) => (current === line.key ? null : line.key))}
                    >
                      <i style={{ backgroundColor: line.color }} />{line.name}
                      <em>{val != null ? formatTpmMillionsTip(val) : '-'}</em>
                    </span>
                  );
                })}
              </div>
            )}
          />

        </section>
        <section className="wire-card realtime-panel realtime-runtime-panel idle-fit-panel">
          <div className="idle-fit-title-row">
            <div className="wire-card-title">重点客户拟合波形</div>
            <Form layout="inline" className="idle-fit-filter">
              <Form.Item label="模型">
                <Select
                  value={selectedFitModel}
                  onChange={(model) => {
                    setSelectedFitModel(model);
                    setSelectedCustomerKey(null);
                  }}

                  options={customerWaves.map((item) => ({ label: item.model, value: item.model }))}

                />
              </Form.Item>

            </Form>
          </div>
          <RuntimeLineChart
            title={`${selectedCustomerFitWave.model} 重点客户${isBusy ? '忙时' : '闲时'}模拟`}
            data={selectedCustomerFitWave.data}
            lines={selectedCustomerFitWave.lines}
            yDomain={selectedCustomerFitWave.yDomain}
            yTicks={selectedCustomerFitWave.yTicks}
            yFormatter={formatTpm}
            tooltipSingleKey={selectedCustomerKey}
            selectedLineKey={activeCustomerKey}
            referenceLines={selectedWatermark ? [{ key: `${selectedWatermark.key}-self-watermark`, name: `${selectedWatermark.name} 自建水位线`, color: selectedWatermark.color, value: selectedWatermark.selfWatermark, strokeDasharray: '6 6' }] : []}
            onLineClick={(key) => setSelectedCustomerKey((current) => (current === key ? null : key))}
            forceSolidLines

          />

          {renderCustomerDispatchRatios(selectedCustomerFitWave)}
        </section>
      </div>
    );
  };

  return (
    <>
      <PageHeader eyebrow="Resources" title="资源看板" description="资源信息与客户模型实时、闲时、忙时跑量拟合。" />
      <div className="resource-board page-section">
        <section className="resource-section resource-section-info">
          <div className="resource-section-title">资源信息</div>
          <div className="realtime-board resource-section-grid resource-info-grid">
            {renderSelfHostedCluster('realtime')}
            {renderVendorRuntime()}
          </div>
        </section>
        <section className="resource-section resource-section-runtime">
          <div className="resource-section-title">客户模型跑量与资源拟合</div>
          <div className="realtime-board resource-section-grid">
            {renderCustomerModelRuntime()}
            {renderFitRuntime('idle')}
            {renderFitRuntime('busy')}
          </div>
        </section>
      </div>
    </>
  );
}
