import { Form, Input, InputNumber, message, Select } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { dashboardsApi, vendorsApi } from '../../api/kongming';
import type { ResourceCluster, VendorQuota } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { numberText, percent } from '../../utils/format';

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
  selectedLineKey?: string | null;
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

const clusterFitData = [
  { time: '00:00', glm51Fp8: 178000, glm51Kscc: 190000, glm52: 166000, kimi: 184000 },
  { time: '01:00', glm51Fp8: 138000, glm51Kscc: 152000, glm52: 130000, kimi: 144000 },
  { time: '02:00', glm51Fp8: 116000, glm51Kscc: 127000, glm52: 110000, kimi: 121000 },
  { time: '03:00', glm51Fp8: 101000, glm51Kscc: 108000, glm52: 98000, kimi: 105000 },
  { time: '04:00', glm51Fp8: 96000, glm51Kscc: 101000, glm52: 92000, kimi: 99000 },
  { time: '05:00', glm51Fp8: 146000, glm51Kscc: 158000, glm52: 136000, kimi: 151000 },
  { time: '06:00', glm51Fp8: 254000, glm51Kscc: 276000, glm52: 238000, kimi: 266000 },
  { time: '07:00', glm51Fp8: 356000, glm51Kscc: 382000, glm52: 334000, kimi: 398000 },
  { time: '08:00', glm51Fp8: 328000, glm51Kscc: 362000, glm52: 316000, kimi: 372000 },
];

const clusterFitLines: FitWaveLine[] = [
  { key: 'glm51Fp8', name: 'GLM-5.1-FP8', color: '#27d7ff' },
  { key: 'glm51Kscc', name: 'GLM-5.1-KSCC', color: '#5dffb2' },
  { key: 'glm52', name: 'GLM-5.2', color: '#f5d54b', strokeDasharray: '5 5' },
  { key: 'kimi', name: 'Kimi-K2.5-MIHAYOU', color: '#9b8cff' },
];

const customerFitWaves: CustomerFitWave[] = [
  {
    model: 'GLM-5.1',
    yDomain: [0, 260000],
    yTicks: [0, 65000, 130000, 195000, 260000],
    data: [
      { time: '00:00', bodhimind: 106000, kscc: 86000, xishanju: 62000, mihayou: 52000 },
      { time: '01:00', bodhimind: 82000, kscc: 72000, xishanju: 54000, mihayou: 47000 },
      { time: '02:00', bodhimind: 69000, kscc: 61000, xishanju: 48000, mihayou: 42000 },
      { time: '03:00', bodhimind: 62000, kscc: 56000, xishanju: 43000, mihayou: 39000 },
      { time: '04:00', bodhimind: 60000, kscc: 52000, xishanju: 41000, mihayou: 37000 },
      { time: '05:00', bodhimind: 89000, kscc: 76000, xishanju: 58000, mihayou: 51000 },
      { time: '06:00', bodhimind: 146000, kscc: 126000, xishanju: 94000, mihayou: 88000 },
      { time: '07:00', bodhimind: 214000, kscc: 172000, xishanju: 128000, mihayou: 116000 },
      { time: '08:00', bodhimind: 198000, kscc: 164000, xishanju: 120000, mihayou: 109000 },
    ],
    lines: [
      { key: 'bodhimind', name: 'BODHIMIND SDN.BHD.', color: '#27d7ff' },
      { key: 'kscc', name: 'KSCC', color: '#5dffb2' },
      { key: 'xishanju', name: '西山居', color: '#f5d54b', strokeDasharray: '5 5' },
      { key: 'mihayou', name: '米哈游', color: '#ff8ab3' },
    ],
    ratios: [
      { key: 'bodhimind', name: 'BODHIMIND SDN.BHD.', color: '#27d7ff', selfRatio: 0.72, vendorRatio: 0.28 },
      { key: 'kscc', name: 'KSCC', color: '#5dffb2', selfRatio: 0.84, vendorRatio: 0.16 },
      { key: 'xishanju', name: '西山居', color: '#f5d54b', selfRatio: 0.68, vendorRatio: 0.32 },
      { key: 'mihayou', name: '米哈游', color: '#ff8ab3', selfRatio: 0.76, vendorRatio: 0.24 },
    ],
  },
  {
    model: 'GLM-5.2',
    yDomain: [0, 520000],
    yTicks: [0, 130000, 260000, 390000, 520000],
    data: [
      { time: '00:00', bodhimind: 186000, tencent: 162000, gameOps: 126000, searchLab: 94000 },
      { time: '01:00', bodhimind: 146000, tencent: 130000, gameOps: 98000, searchLab: 76000 },
      { time: '02:00', bodhimind: 124000, tencent: 108000, gameOps: 88000, searchLab: 68000 },
      { time: '03:00', bodhimind: 104000, tencent: 92000, gameOps: 76000, searchLab: 62000 },
      { time: '04:00', bodhimind: 99000, tencent: 88000, gameOps: 72000, searchLab: 58000 },
      { time: '05:00', bodhimind: 152000, tencent: 136000, gameOps: 108000, searchLab: 84000 },
      { time: '06:00', bodhimind: 282000, tencent: 248000, gameOps: 196000, searchLab: 146000 },
      { time: '07:00', bodhimind: 428000, tencent: 362000, gameOps: 276000, searchLab: 204000 },
      { time: '08:00', bodhimind: 398000, tencent: 344000, gameOps: 254000, searchLab: 188000 },
    ],
    lines: [
      { key: 'bodhimind', name: 'BODHIMIND SDN.BHD.', color: '#27d7ff' },
      { key: 'tencent', name: '腾讯云游戏', color: '#5dffb2' },
      { key: 'gameOps', name: '游戏运营平台', color: '#f5d54b', strokeDasharray: '5 5' },
      { key: 'searchLab', name: '搜索实验室', color: '#9b8cff' },
    ],
    ratios: [
      { key: 'bodhimind', name: 'BODHIMIND SDN.BHD.', color: '#27d7ff', selfRatio: 0.64, vendorRatio: 0.36 },
      { key: 'tencent', name: '腾讯云游戏', color: '#5dffb2', selfRatio: 0.71, vendorRatio: 0.29 },
      { key: 'gameOps', name: '游戏运营平台', color: '#f5d54b', selfRatio: 0.58, vendorRatio: 0.42 },
      { key: 'searchLab', name: '搜索实验室', color: '#9b8cff', selfRatio: 0.82, vendorRatio: 0.18 },
    ],
  },
  {
    model: 'Kimi-k2.5',
    yDomain: [0, 360000],
    yTicks: [0, 90000, 180000, 270000, 360000],
    data: [
      { time: '00:00', mihayou: 134000, kscc: 112000, contentOps: 76000, qa: 52000 },
      { time: '01:00', mihayou: 104000, kscc: 89000, contentOps: 62000, qa: 46000 },
      { time: '02:00', mihayou: 92000, kscc: 78000, contentOps: 54000, qa: 41000 },
      { time: '03:00', mihayou: 84000, kscc: 70000, contentOps: 50000, qa: 38000 },
      { time: '04:00', mihayou: 80000, kscc: 66000, contentOps: 48000, qa: 36000 },
      { time: '05:00', mihayou: 126000, kscc: 98000, contentOps: 70000, qa: 51000 },
      { time: '06:00', mihayou: 218000, kscc: 166000, contentOps: 116000, qa: 82000 },
      { time: '07:00', mihayou: 314000, kscc: 236000, contentOps: 164000, qa: 112000 },
      { time: '08:00', mihayou: 292000, kscc: 224000, contentOps: 152000, qa: 104000 },
    ],
    lines: [
      { key: 'mihayou', name: '米哈游', color: '#27d7ff' },
      { key: 'kscc', name: 'KSCC', color: '#5dffb2' },
      { key: 'contentOps', name: '内容运营', color: '#f5d54b', strokeDasharray: '5 5' },
      { key: 'qa', name: '评测任务', color: '#ff8ab3' },
    ],
    ratios: [
      { key: 'mihayou', name: '米哈游', color: '#27d7ff', selfRatio: 0.79, vendorRatio: 0.21 },
      { key: 'kscc', name: 'KSCC', color: '#5dffb2', selfRatio: 0.67, vendorRatio: 0.33 },
      { key: 'contentOps', name: '内容运营', color: '#f5d54b', selfRatio: 0.74, vendorRatio: 0.26 },
      { key: 'qa', name: '评测任务', color: '#ff8ab3', selfRatio: 0.61, vendorRatio: 0.39 },
    ],
  },
];

const busyFitTimes = ['08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00', '24:00'];

function retimeFitData(data: Array<Record<string, number | string>>, times: string[]) {
  return data.map((point, index) => ({ ...point, time: times[index] || String(point.time) }));
}

const busyClusterFitData = retimeFitData(clusterFitData, busyFitTimes);
const busyCustomerFitWaves: CustomerFitWave[] = customerFitWaves.map((wave) => ({
  ...wave,
  data: retimeFitData(wave.data, busyFitTimes),
}));


function formatTpm(value: number) {
  if (value >= 1000000) return `${Number((value / 1000000).toFixed(1))} Mil`;
  if (value >= 1000) return `${Number((value / 1000).toFixed(0))} K`;
  return String(value);
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

function buildVendorModelGroups(rows: VendorRuntimeRow[]): VendorModelGroup[] {
  return Array.from(new Set(rows.map((row) => row.modelName))).map((modelName) => {
    const groupRows = rows.filter((row) => row.modelName === modelName);
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
    modelName: row.model,
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

function RuntimeLineChart({ title, data, lines, summary, yDomain, yTicks, yFormatter, selectedLineKey, referenceLines, onLineClick, forceSolidLines }: RuntimeLineChartProps) {

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
            {referenceLines?.map((line) => (
              <ReferenceLine key={line.key} y={line.value} stroke={line.color} strokeDasharray={line.strokeDasharray || '6 6'} strokeOpacity={0.45} strokeWidth={2} ifOverflow="extendDomain" />
            ))}
            {lines.map((line) => {
              const isSelected = selectedLineKey === line.key;
              const isDimmed = Boolean(selectedLineKey && !isSelected);
              return (
                <Line
                  key={line.key}
                  type="monotone"
                  dataKey={line.key}
                  name={line.name}
                  stroke={line.color}
                  strokeWidth={isSelected ? 2.6 : 2}
                  strokeDasharray={forceSolidLines ? undefined : line.strokeDasharray}
                  strokeOpacity={isDimmed ? 0.38 : 1}

                  dot={false}
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
      {summary ? (

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

const resourceSections: Array<{ title: string; period: ResourcePeriod }> = [
  { title: '实时资源', period: 'realtime' },
  { title: '闲时资源', period: 'idle' },
  { title: '忙时资源', period: 'busy' },
];

export function RealtimeDashboard() {
  const [selfHostedRows, setSelfHostedRows] = useState<SelfHostedClusterRow[]>(() => baseSelfHostedRows.map(normalizeClusterRow));
  const [vendorRows, setVendorRows] = useState<VendorRuntimeRow[]>([]);
  const [savingClusterId, setSavingClusterId] = useState<string | null>(null);
  const [selectedFitModel, setSelectedFitModel] = useState(customerFitWaves[0].model);
  const [selectedCustomerKey, setSelectedCustomerKey] = useState<string | null>(null);

  const vendorMetrics = useMemo(() => buildVendorMetrics(vendorRows), [vendorRows]);


  useEffect(() => {
    let cancelled = false;
    dashboardsApi.resources({}).then((data) => {
      if (cancelled || !data.clusters?.length) return;
      setSelfHostedRows((rows) => rows.map((row) => {
        const cluster = data.clusters?.find((item) => item.cluster_name === row.clusterName && item.deployed_model === row.deployedModel);
        if (!cluster) return row;
        return mergeClusterResponse(row, cluster);
      }));
    }).catch(() => undefined);
    vendorsApi.quotas({ status: 'active', page_size: 100 }).then((data) => {
      if (cancelled) return;
      setVendorRows(data.items.map(mapVendorQuota));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const saveTpmPerMachine = async (record: SelfHostedClusterRow, value: number | null) => {
    const nextValue = Number(value || 0);
    if (nextValue === record.tpmPerMachine) return;
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
      message.success('单机承载能力已保存');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '单机承载能力保存失败');
    } finally {
      setSavingClusterId(null);
    }
  };

  const renderTpmInput = (record: SelfHostedClusterRow) => (
    <InputNumber
      key={`${record.id}-${record.tpmPerMachine}`}
      className="realtime-cell-number"
      min={0}
      size="small"
      defaultValue={Number(record.tpmPerMachine || 0)}
      disabled={savingClusterId === record.id}
      onPressEnter={(event) => event.currentTarget.blur()}
      onBlur={(event) => saveTpmPerMachine(record, Number(event.currentTarget.value))}
    />
  );

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
    const customerWaves = isBusy ? busyCustomerFitWaves : customerFitWaves;
    const selectedCustomerFitWave = customerWaves.find((item) => item.model === selectedFitModel) || customerWaves[0];
    const watermarks = getCustomerWatermarks(selectedCustomerFitWave);
    const selectedWatermark = watermarks.find((item) => item.key === selectedCustomerKey) || null;
    const activeCustomerKey = selectedWatermark?.key || null;

    return (
      <div className="idle-fit-module-stack">
        <section className="wire-card realtime-panel realtime-runtime-panel idle-fit-panel">

          <div className="wire-card-title">集群拟合波形</div>
          <RuntimeLineChart
            title={isBusy ? '忙时跑量预估（08:00-24:00）' : '闲时跑量预估'}
            data={isBusy ? busyClusterFitData : clusterFitData}
            lines={clusterFitLines}
            yDomain={isBusy ? [0, 720000] : [0, 600000]}
            yTicks={isBusy ? [0, 180000, 360000, 540000, 720000] : [0, 150000, 300000, 450000, 600000]}
            yFormatter={formatTpm}
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

                  options={customerFitWaves.map((item) => ({ label: item.model, value: item.model }))}
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
      <PageHeader eyebrow="Resources" title="资源看板" description="按实时、闲时、忙时展示自建集群、三方供应商和客户模型跑量。" />
      <div className="resource-board page-section">
        {resourceSections.map((section) => (
          <section className={`resource-section resource-section-${section.period}`} key={section.title}>
            <div className="resource-section-title">{section.title}</div>
            <div className="realtime-board resource-section-grid">
              {renderSelfHostedCluster(section.period)}
              {renderVendorRuntime()}
              {section.period === 'idle' || section.period === 'busy' ? renderFitRuntime(section.period) : renderCustomerModelRuntime()}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
