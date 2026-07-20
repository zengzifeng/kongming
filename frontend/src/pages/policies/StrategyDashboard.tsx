import { Button, Drawer, Form, Input, InputNumber, message, Modal, Select, Space, Spin, Table } from 'antd';
import { CheckCircleOutlined, DeleteOutlined, EditOutlined, EyeOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';


import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';

import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { evaluationsApi, fittingsApi, jobsApi, policiesApi } from '../../api/kongming';
import type { Evaluation, FittingConfig, JobSchedule, Policy, PolicyDetail } from '../../api/types';

import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText, percent, ratioPercent } from '../../utils/format';

type StrategyTemplateKey = 'demand_evaluation' | 'idle' | 'busy';

const demandEvaluationStrategyLabel = '实时策略';
const legacyDemandEvaluationStrategyLabel = '需求评估策略';

const strategyTemplateOptions: Array<{ label: string; value: StrategyTemplateKey; algorithm: string }> = [
  { label: demandEvaluationStrategyLabel, value: 'demand_evaluation', algorithm: 'demand_evaluation' },
  { label: '闲时策略', value: 'idle', algorithm: 'time_period' },
  { label: '忙时策略', value: 'busy', algorithm: 'time_period' },
];

type StrategyPlanKind = 'demand' | 'idle' | 'busy';


interface StrategyFlow {
  source: string;
  sourceModel: string;
  sourceRate: string;
  sourceMachinesBefore: number;
  sourceMachinesAfter: number;
  target: string;
  targetModel: string;
  targetRate: string;
  targetMachinesBefore: number;
  targetMachinesAfter: number;
  machines: number;
  sourceUtilizationBefore?: number;
  sourceUtilizationAfter?: number;
  targetUtilizationBefore?: number;
  targetUtilizationAfter?: number;
  gain: number;
}

interface StrategyAttribution {
  customer: string;
  customerName: string;
  uid: string;
  model: string;
  pricePerMillionTokens: number;
  marginalRevenue: number;
  unitSelfRevenue: number;
  density: number;
  beforeRatio: number;
  afterRatio: number;
  watermarkBefore: number;
  watermark: number;
  beforeVolume: number;
  afterVolume: number;
  deltaVolume: number;
  beforeArea: number;
  afterArea: number;
  deltaArea: number;
  gain: number;
  fallback: string;
  series: number[];
}

interface FittingStrategy {
  id: string;
  customerName: string;
  modelName: string;
  fittingAlgorithm: string;
  manualParams: string;
}


interface StrategyUtilRow {
  cluster: string;
  model: string;
  capacityBefore: string;
  capacityAfter: string;
  utilizationBefore: number;
  utilizationAfter: number;
}

interface StrategyPlan {
  id: string;
  kind: StrategyPlanKind;
  title: string;
  subtitle: string;
  policyNo: string;
  window: string;
  generatedAt: string | null;
  expectedGain: number;
  status: string;
  flows: StrategyFlow[];
  attributions: StrategyAttribution[];
  utilRows: StrategyUtilRow[];
  detailLead: string;
}

interface ScheduledTask {
  id: string;
  taskName: string;
  algorithm: string;
  frequency: string;
  executeTime: string;
  status: string;
  triggerType: string;
  cronExpr: string | null;
  intervalSeconds: number | null;
}

interface StrategyEditFormValues {
  flows?: Array<{ machines?: number }>;
  attributions?: Array<{ watermark?: number }>;
}

interface ScheduledTaskFormValues {
  taskName: string;
  frequencyKey: string;
  executeTimeKey: string;
  status: string;
}

const scheduledTaskStatusLabels: Record<string, string> = {
  running: '运行中',
  scheduled: '待执行',
  paused: '已暂停',
  failed: '异常',
};

const taskFrequencyOptions = [
  { label: '每 1 分钟', value: 'interval_60', triggerType: 'interval', intervalSeconds: 60 },
  { label: '每 5 分钟', value: 'interval_300', triggerType: 'interval', intervalSeconds: 300 },
  { label: '每 15 分钟', value: 'interval_900', triggerType: 'interval', intervalSeconds: 900 },
  { label: '每 30 分钟', value: 'interval_1800', triggerType: 'interval', intervalSeconds: 1800 },
  { label: '每小时', value: 'hourly', triggerType: 'cron' },
  { label: '每天', value: 'daily', triggerType: 'cron' },
  { label: '每周一', value: 'weekly_monday', triggerType: 'cron' },
  { label: '每月 1 日', value: 'monthly_first', triggerType: 'cron' },
];

const taskExecuteTimeOptions: Record<string, Array<{ label: string; value: string }>> = {
  interval_60: [{ label: '按间隔执行', value: 'interval' }],
  interval_300: [{ label: '按间隔执行', value: 'interval' }],
  interval_900: [{ label: '按间隔执行', value: 'interval' }],
  interval_1800: [{ label: '按间隔执行', value: 'interval' }],
  hourly: [0, 5, 10, 15, 30, 45].map((minute) => ({ label: `每小时第 ${String(minute).padStart(2, '0')} 分`, value: String(minute) })),
  daily: ['00:00', '01:00', '02:00', '08:00', '12:00', '18:00', '23:00'].map((time) => ({ label: time, value: time })),
  weekly_monday: ['08:00', '09:00', '10:00'].map((time) => ({ label: `周一 ${time}`, value: time })),
  monthly_first: ['08:00', '09:00', '10:00'].map((time) => ({ label: `1 日 ${time}`, value: time })),
};


function policyText(policy: Policy) {
  return `${policy.algorithm} ${policy.policy_no} ${JSON.stringify(policy.summary_json || {})}`;
}

function summaryField(policy: Policy, key: string) {
  const value = policy.summary_json?.[key];
  return typeof value === 'string' ? value : '';
}

function arrayField(source: Record<string, unknown> | undefined, key: string): Record<string, unknown>[] {
  const value = source?.[key];
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null) : [];
}

function objectField(source: Record<string, unknown> | undefined, key: string): Record<string, unknown> | undefined {
  const value = source?.[key];
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function taskStatus(schedule: JobSchedule) {
  if (!schedule.enabled) return 'paused';
  return schedule.last_run_at ? 'running' : 'scheduled';
}

function formatInterval(seconds: number) {
  if (seconds < 60) return `每 ${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const restSeconds = seconds % 60;
  if (minutes < 60) return restSeconds ? `每 ${minutes} 分 ${restSeconds} 秒` : `每 ${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `每 ${hours} 小时 ${restMinutes} 分钟` : `每 ${hours} 小时`;
}

function parseCron(expr?: string | null) {
  const [minute, hour, day, month, week] = (expr || '').trim().split(/\s+/);
  return { minute, hour, day, month, week, valid: Boolean(minute && hour && day && month && week) };
}

function cronTimeLabel(expr?: string | null) {
  const cron = parseCron(expr);
  if (!cron.valid) return expr || '-';
  const minute = cron.minute.padStart(2, '0');
  if (cron.hour === '*') return `每小时第 ${minute} 分`;
  return `${cron.hour.padStart(2, '0')}:${minute}`;
}

function cronFrequencyLabel(expr?: string | null) {
  const cron = parseCron(expr);
  if (!cron.valid) return 'Cron';
  if (cron.day === '*' && cron.month === '*' && cron.week === '*' && cron.hour === '*') return '每小时';
  if (cron.day === '*' && cron.month === '*' && cron.week === '*') return '每天';
  if (cron.day === '*' && cron.month === '*' && cron.week !== '*') return `每周${cron.week}`;
  if (cron.day !== '*' && cron.month === '*' && cron.week === '*') return `每月 ${cron.day} 日`;
  return '定时执行';
}

function taskFrequency(schedule: Pick<JobSchedule, 'trigger_type' | 'interval_seconds' | 'cron_expr'>) {
  if (schedule.trigger_type === 'interval' && schedule.interval_seconds) return formatInterval(schedule.interval_seconds);
  if (schedule.trigger_type === 'cron' && schedule.cron_expr) return cronFrequencyLabel(schedule.cron_expr);
  return schedule.trigger_type;
}

function taskExecuteTime(schedule: Pick<JobSchedule, 'trigger_type' | 'interval_seconds' | 'cron_expr' | 'next_run_at'>) {
  if (schedule.trigger_type === 'cron' && schedule.cron_expr) return cronTimeLabel(schedule.cron_expr);
  if (schedule.trigger_type === 'interval' && schedule.next_run_at) return `下次 ${dateText(schedule.next_run_at)}`;
  if (schedule.trigger_type === 'interval' && schedule.interval_seconds) return '按间隔执行';
  return '-';
}

function scheduleKeysFromTask(task: Pick<ScheduledTask, 'triggerType' | 'cronExpr' | 'intervalSeconds'>) {
  if (task.triggerType === 'interval') return { frequencyKey: `interval_${task.intervalSeconds || 60}`, executeTimeKey: 'interval' };
  const cron = parseCron(task.cronExpr);
  if (!cron.valid) return { frequencyKey: 'hourly', executeTimeKey: '0' };
  if (cron.day === '*' && cron.month === '*' && cron.week === '*' && cron.hour === '*') return { frequencyKey: 'hourly', executeTimeKey: String(Number(cron.minute)) };
  const time = `${cron.hour.padStart(2, '0')}:${cron.minute.padStart(2, '0')}`;
  if (cron.day === '*' && cron.month === '*' && cron.week === '*') return { frequencyKey: 'daily', executeTimeKey: time };
  if (cron.day === '*' && cron.month === '*' && cron.week === '1') return { frequencyKey: 'weekly_monday', executeTimeKey: time };
  if (cron.day === '1' && cron.month === '*' && cron.week === '*') return { frequencyKey: 'monthly_first', executeTimeKey: time };
  return { frequencyKey: 'daily', executeTimeKey: time };
}

function schedulePayload(values: ScheduledTaskFormValues) {
  const option = taskFrequencyOptions.find((item) => item.value === values.frequencyKey) || taskFrequencyOptions[0];
  if (option.triggerType === 'interval') {
    return { trigger_type: 'interval', cron_expr: null, interval_seconds: option.intervalSeconds || 60 };
  }
  const [hour, minute] = values.executeTimeKey.split(':');
  if (values.frequencyKey === 'hourly') return { trigger_type: 'cron', cron_expr: `${values.executeTimeKey} * * * *`, interval_seconds: null };
  if (values.frequencyKey === 'weekly_monday') return { trigger_type: 'cron', cron_expr: `${minute} ${hour} * * 1`, interval_seconds: null };
  if (values.frequencyKey === 'monthly_first') return { trigger_type: 'cron', cron_expr: `${minute} ${hour} 1 * *`, interval_seconds: null };
  return { trigger_type: 'cron', cron_expr: `${minute} ${hour} * * *`, interval_seconds: null };
}

function taskFormInitialValues(task?: ScheduledTask): ScheduledTaskFormValues {
  const keys = task ? scheduleKeysFromTask(task) : { frequencyKey: 'daily', executeTimeKey: '08:00' };
  return { taskName: task?.taskName || '', status: task?.status || 'scheduled', ...keys };
}

function scheduledTaskFromJob(schedule: JobSchedule): ScheduledTask {
  return {
    id: schedule.job_name,
    taskName: schedule.description || schedule.job_name,
    algorithm: schedule.job_name,
    frequency: taskFrequency(schedule),
    executeTime: taskExecuteTime(schedule),
    status: taskStatus(schedule),
    triggerType: schedule.trigger_type,
    cronExpr: schedule.cron_expr,
    intervalSeconds: schedule.interval_seconds,
  };
}

function fittingStrategyFromConfig(config: FittingConfig): FittingStrategy {
  return {
    id: String(config.id),
    customerName: config.ai_consumer,
    modelName: config.model_name,
    fittingAlgorithm: config.algo_name,
    manualParams: JSON.stringify(config.params_json || {}),
  };
}

function uniqueFittingStrategies(configs: FittingConfig[]): FittingStrategy[] {
  const seen = new Set<string>();
  return configs.flatMap((config) => {
    const key = `${config.ai_consumer}::${config.model_name}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [fittingStrategyFromConfig(config)];
  });
}

function strategyEditInitialValues(plan: StrategyPlan): StrategyEditFormValues {
  return {
    flows: plan.flows.map((flow) => ({ machines: flow.machines })),
    attributions: plan.attributions.map((item) => ({ watermark: item.watermark / 10000 })),
  };
}

function applyStrategyEdits(policy: Policy, values: StrategyEditFormValues) {
  const summary = { ...(policy.summary_json || {}) };
  const flowMachines = values.flows || [];
  const watermarkRows = values.attributions || [];
  const patchMoves = (rows: unknown) => Array.isArray(rows)
    ? rows.map((row, index) => typeof row === 'object' && row !== null
      ? { ...(row as Record<string, unknown>), machine_count: Number(flowMachines[index]?.machines ?? numberField(row as Record<string, unknown>, 'machine_count', 1)) }
      : row)
    : rows;
  const patchWatermarks = (rows: unknown) => Array.isArray(rows)
    ? rows.map((row, index) => {
      if (typeof row !== 'object' || row === null) return row;
      const record = row as Record<string, unknown>;
      const nextWatermark = Number(watermarkRows[index]?.watermark ?? numberField(record, 'watermark_after', numberField(record, 'watermark', numberField(record, 'watermark_self_tpm'))) / 10000) * 10000;
      return {
        ...record,
        watermark_after: nextWatermark,
        watermark: nextWatermark,
        watermark_self_tpm: nextWatermark,
        delta: nextWatermark - numberField(record, 'watermark_before', numberField(record, 'before_watermark', nextWatermark)),
      };
    })
    : rows;

  summary.node_moves = patchMoves(summary.node_moves);
  summary.watermark_changes = patchWatermarks(summary.watermark_changes);
  summary.accepted_customers = patchWatermarks(summary.accepted_customers);
  const rb = objectField(summary, 'model_rebalance');
  if (rb) {
    summary.model_rebalance = {
      ...rb,
      moves: patchMoves(rb.moves),
      customer_watermark_delta: patchWatermarks(rb.customer_watermark_delta),
    };
  }
  return summary;
}

function isIdlePolicy(policy: Policy) {

  if (policy.scenario) return policy.scenario === 'idle';
  const text = policyText(policy);
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return policy.algorithm === 'off_peak' || module === 'idle' || ['闲时策略', '闲忙时策略'].includes(template) || text.includes('闲时');
}

function isBusyPolicy(policy: Policy) {
  if (policy.scenario) return policy.scenario === 'busy';
  const text = policyText(policy);
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return module === 'busy' || template === '忙时策略' || (policy.algorithm === 'time_period' && !isIdlePolicy(policy)) || (text.includes('忙时') && !isIdlePolicy(policy));
}

function isDemandEvaluationPolicy(policy: Policy) {
  if (policy.scenario) return policy.scenario === 'demand_evaluation';
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return policy.algorithm === 'demand_evaluation' || module === 'demand_evaluation' || [demandEvaluationStrategyLabel, legacyDemandEvaluationStrategyLabel].includes(template);
}

function stringField(source: Record<string, unknown> | undefined, key: string, fallback = '') {
  const value = source?.[key];
  return value === undefined || value === null ? fallback : String(value);
}

function numberField(source: Record<string, unknown> | undefined, key: string, fallback = 0) {
  const value = Number(source?.[key]);
  return Number.isFinite(value) ? value : fallback;
}

function demandEvaluationStatus(policy: Policy, evaluation?: Evaluation) {
  if (policy.status === 'accepted') return 'approved';
  if (policy.status === 'cancelled') return 'rejected';
  if (evaluation?.status === 'draft') return 'evaluating';
  return 'pending';
}


const demandEvaluationStatusLabels: Record<string, string> = {
  pending: '待评估',
  evaluating: '评估中',
  approved: '确认',
  rejected: '驳回',
};

function flowFromMove(move: Record<string, unknown>, policy: Policy, index: number): StrategyFlow {
  const summary = policy.summary_json || {};
  const machinesBefore = objectField(summary, 'machines_before');
  const machinesAfter = objectField(summary, 'machines_after');
  const source = stringField(move, 'from_cluster', '源集群');
  const target = stringField(move, 'to_cluster', '目标集群');
  const sourceMachinesBefore = numberField(machinesBefore, source);
  const sourceMachinesAfter = numberField(machinesAfter, source, Math.max(sourceMachinesBefore - numberField(move, 'machine_count'), 0));
  const targetMachinesBefore = numberField(machinesBefore, target);
  const targetMachinesAfter = numberField(machinesAfter, target, targetMachinesBefore + numberField(move, 'machine_count'));
  return {
    source,
    sourceModel: stringField(move, 'from_model', stringField(move, 'source_model', '-')),
    sourceRate: `${formatTpm(numberField(move, 'from_tpm_per_machine'))}/台`,
    sourceMachinesBefore,
    sourceMachinesAfter,
    sourceUtilizationBefore: numberField(move, 'source_utilization_before'),
    sourceUtilizationAfter: numberField(move, 'source_utilization_after'),
    target,
    targetModel: stringField(move, 'model', stringField(move, 'to_model', '-')),
    targetRate: `${formatTpm(numberField(move, 'to_tpm_per_machine'))}/台`,
    targetMachinesBefore,
    targetMachinesAfter,
    targetUtilizationBefore: numberField(move, 'target_utilization_before'),
    targetUtilizationAfter: numberField(move, 'target_utilization_after'),

    machines: numberField(move, 'machine_count', 1),
    gain: numberField(move, 'gain_yuan_day', numberField(move, 'gain', Number(policy.expected_revenue_gain || 0) / Math.max(index + 1, 1))),
  };
}

function slotHour(slot: Record<string, unknown>): number {
  const raw = slot['hour'];
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  const ts = stringField(slot, 'ts', stringField(slot, 'time', ''));
  // ts 形如 "2026-07-19T09:00:00"，直接截取小时位，避免时区解析偏移。
  if (ts.length >= 13 && ts[10] === 'T') {
    const hour = Number(ts.slice(11, 13));
    if (Number.isFinite(hour)) return hour;
  }
  const parsed = new Date(ts);
  return Number.isNaN(parsed.getTime()) ? -1 : parsed.getHours();
}

// 用后端 watermark_changes 行里的逐时 slots 还原客户实跑波形（按 ts 小时落到 0..23）；
// 无 slots 的行（如 accepted_customers / customer_watermark_delta）返回 null，由调用方回退。
function hourlySeriesFromSlots(slots: Record<string, unknown>[]): number[] | null {
  if (!slots.length) return null;
  const series = Array.from({ length: 24 }, () => 0);
  let matched = false;
  slots.forEach((slot) => {
    const hour = slotHour(slot);
    if (hour < 0 || hour > 23) return;
    series[hour] = numberField(slot, 'tpm', numberField(slot, 'self_tpm', 0));
    matched = true;
  });
  return matched ? series : null;
}

function attributionFromWatermark(row: Record<string, unknown>, policy: Policy, index: number): StrategyAttribution {
  // 后端 watermark_changes 行用 watermark_self_tpm / current_self_ratio / customer_revenue_gain；
  // model_rebalance.customer_watermark_delta 行用 watermark_before / watermark_after / delta。
  // 两种形状都要能解析，否则量会整体塌成 0。
  const after = numberField(row, 'watermark_after', numberField(row, 'watermark', numberField(row, 'watermark_self_tpm')));
  const selfRatio = numberField(row, 'current_self_ratio', NaN);
  const beforeDefault = Number.isFinite(selfRatio) ? after * selfRatio : after;
  const before = numberField(row, 'watermark_before', numberField(row, 'before_watermark', beforeDefault));
  const delta = numberField(row, 'delta', after - before);
  const gain = numberField(row, 'gain_yuan_day', numberField(row, 'customer_revenue_gain', Number(policy.expected_revenue_gain || 0) / Math.max(index + 1, 1)));
  const base = Math.max(before, after, 1);
  const series = hourlySeriesFromSlots(arrayField(row, 'slots')) ?? Array.from({ length: 24 }, () => Math.max(before, after));
  const beforeArea = series.reduce((sum, demand) => sum + Math.min(demand, before), 0) / 10000;
  const afterArea = series.reduce((sum, demand) => sum + Math.min(demand, after), 0) / 10000;

  const uid = stringField(row, 'customer_code', stringField(row, 'report_id', '-'));
  const customerName = stringField(row, 'customer_name', stringField(row, 'customer', uid));
  const customerLabel = customerName && customerName !== uid ? `${customerName}（${uid}）` : uid;
  const unitSelfRevenue = numberField(row, 'unit_self_revenue', 0);

  return {
    customer: customerLabel,
    customerName,
    uid,
    model: stringField(row, 'model', stringField(row, 'model_name', '-')),
    pricePerMillionTokens: unitSelfRevenue,
    marginalRevenue: gain,
    unitSelfRevenue,
    density: delta ? gain / delta : 0,
    beforeRatio: before / base,
    afterRatio: after / base,
    watermarkBefore: before,
    watermark: after,
    beforeVolume: before / 10000,
    afterVolume: after / 10000,
    deltaVolume: delta / 10000,
    beforeArea,
    afterArea,
    deltaArea: afterArea - beforeArea,
    gain,
    fallback: stringField(row, 'fallback', stringField(row, 'reason', '-')),
    // 优先用后端逐时 slots 还原真实波形；无 slots 才回退到峰值水位线的平直线。
    series,
  };
}

function uniqueRecords(rows: Record<string, unknown>[], keys: string[]) {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = keys.map((item) => String(row[item] ?? '')).join('::');
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function utilRowsFromPolicy(policy: Policy): StrategyUtilRow[] {
  const rb = objectField(policy.summary_json, 'model_rebalance');
  const clusters = arrayField(rb, 'per_cluster');
  return clusters.map((cluster) => ({
    cluster: stringField(cluster, 'cluster_name', '-'),
    model: stringField(cluster, 'model', '-'),
    capacityBefore: `${numberText(numberField(cluster, 'machines_before') * numberField(cluster, 'rate') / 10000)}w`,
    capacityAfter: `${numberText(numberField(cluster, 'machines_after') * numberField(cluster, 'rate') / 10000)}w`,
    utilizationBefore: 0,
    utilizationAfter: 0,
  }));
}

function timePeriodPlanFromPolicy(policy: Policy, kind: Extract<StrategyPlanKind, 'idle' | 'busy'>): StrategyPlan {
  const summary = policy.summary_json || {};
  const rb = objectField(summary, 'model_rebalance');
  // node_moves 已是「机器重分配 + 模型级再平衡」按集群粒度聚合后的完整列表，直接用它即可，
  // 不再并入 rb.moves（那是再平衡子集，合并会导致同一源→目集群重复展示）。
  const moves = arrayField(summary, 'node_moves');
  // 按 (customer_code, model) 去重：同一客户可能同时出现在 watermark_changes（D阶段最终水位，带真实
  // customer_revenue_gain + slots）和 model_rebalance.customer_watermark_delta（C2再平衡归因，无 gain）。
  // watermark_changes 排在前 → 保留它、丢掉 rebalance-delta 的重复行，避免同一客户两行且密度不一致。
  const watermarkChanges = uniqueRecords([...arrayField(summary, 'watermark_changes'), ...arrayField(rb, 'customer_watermark_delta'), ...arrayField(summary, 'accepted_customers')], ['customer_code', 'model']);
  const expectedGain = kind === 'idle' ? Number(policy.expected_off_peak_gain || policy.expected_revenue_gain || 0) : Number(policy.expected_revenue_gain || 0);
  return {
    id: `${kind}-${policy.id}`,
    kind,
    title: stringField(summary, 'title', kind === 'idle' ? '闲时策略方案' : '忙时策略方案'),
    subtitle: stringField(summary, 'description', stringField(summary, 'reason', '')),
    policyNo: policy.policy_no,
    window: stringField(summary, 'window', kind === 'idle' ? '闲时窗口' : '忙时窗口'),
    generatedAt: policy.created_at || null,
    expectedGain,
    status: policy.status,
    flows: moves.map((move, index) => flowFromMove(move, policy, index)),
    // 逐调整收益核算按「百万token单价」降序——与求解器承接优先级(C阶段候选排序键)一致。
    attributions: watermarkChanges.map((row, index) => attributionFromWatermark(row, policy, index))
      .sort((a, b) => b.unitSelfRevenue - a.unitSelfRevenue || b.gain - a.gain),
    utilRows: utilRowsFromPolicy(policy),
    detailLead: kind === 'idle' ? '闲时策略来自后端时段策略摘要。' : '忙时策略来自后端时段策略摘要。',
  };
}

function demandEvaluationPlanFromPolicy(policy: Policy, evaluation?: Evaluation): StrategyPlan {

  const summary = policy.summary_json || {};
  const actionPayload = {
    demand_id: numberField(summary, 'demand_id'),
    report_id: stringField(summary, 'report_id', '未知需求'),
    model: stringField(summary, 'model', stringField(summary, 'model_name', '评估模型')),
    expected_tpm: numberField(summary, 'expected_tpm'),
    feasibility_score: evaluation?.feasibility_score ?? numberField(summary, 'feasibility_score'),
    benefit_score: evaluation?.customer_value_score ?? numberField(summary, 'benefit_score'),
    expected_revenue: evaluation?.expected_revenue ?? numberField(summary, 'expected_revenue'),
    expected_cost: evaluation?.expected_cost ?? numberField(summary, 'expected_cost'),
    expected_margin: evaluation?.expected_margin ?? numberField(summary, 'expected_margin', policy.expected_revenue_gain),
    recommendation: evaluation?.recommendation || stringField(summary, 'recommendation', 'manual_review'),
  };
  const expectedGain = Number(actionPayload.expected_margin || policy.expected_revenue_gain || 0);
  const feasibility = Number(actionPayload.feasibility_score || 0);
  const benefit = Number(actionPayload.benefit_score || 0);
  const tpm = Number(actionPayload.expected_tpm || 0);
  const reportId = actionPayload.report_id;
  const status = demandEvaluationStatus(policy, evaluation);

  return {
    id: `demand-${policy.id}`,
    kind: 'demand',
    title: `${reportId} 需求评估方案`,
    subtitle: '',
    policyNo: policy.policy_no,
    window: stringField(summary, 'window', '按需求期望时间执行'),
    generatedAt: policy.created_at || null,
    expectedGain,
    status,
    flows: [
      { source: '需求报备', sourceModel: reportId, sourceRate: `${formatTpm(tpm)} TPM`, sourceMachinesBefore: 0, sourceMachinesAfter: Math.max(1, Math.ceil(tpm / 100000)), machines: Math.max(1, Math.ceil(tpm / 100000)), target: demandEvaluationStrategyLabel, targetModel: actionPayload.model, targetRate: `可行性 ${percent(feasibility)}`, targetMachinesBefore: 0, targetMachinesAfter: Math.max(1, Math.ceil(tpm / 100000)), sourceUtilizationBefore: feasibility, sourceUtilizationAfter: benefit, targetUtilizationBefore: feasibility, targetUtilizationAfter: benefit, gain: expectedGain },
    ],
    attributions: [
      { customer: reportId, customerName: reportId, uid: reportId, model: actionPayload.model, pricePerMillionTokens: 0, marginalRevenue: expectedGain, unitSelfRevenue: 0, density: benefit, beforeRatio: feasibility, afterRatio: benefit, watermarkBefore: Math.round(tpm * feasibility), watermark: tpm, beforeVolume: Number(actionPayload.expected_cost || 0), afterVolume: Number(actionPayload.expected_revenue || 0), deltaVolume: expectedGain, beforeArea: 0, afterArea: 0, deltaArea: 0, gain: expectedGain, fallback: actionPayload.recommendation, series: Array.from({ length: 24 }, (_, hour) => Math.round(tpm * (0.68 + Math.sin((hour / 24) * Math.PI) * 0.28 + (hour % 5) * 0.015))) }, 
    ],
    utilRows: [
      { cluster: '需求评估', model: actionPayload.model, capacityBefore: money(actionPayload.expected_cost), capacityAfter: money(actionPayload.expected_revenue), utilizationBefore: feasibility, utilizationAfter: benefit },
    ],
    detailLead: `${demandEvaluationStrategyLabel}以需求报备、可行性和收益测算为输入。人工确认后需求看板状态变为确认，驳回后同步变为驳回。`,
  };
}

function totalBy<T>(items: T[], selector: (item: T) => number) {

  return items.reduce((sum, item) => sum + selector(item), 0);
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

interface EvaluationModuleProps {
  evaluations: Evaluation[];
  policies: Policy[];
  onCreate: () => void;
  onReload: () => void;
  onOpenPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onAcceptPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onRejectPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onOpenDemand: (demandId: number) => void;
}

function EvaluationModule({ evaluations, policies, onCreate, onReload, onOpenPlan, onAcceptPlan, onRejectPlan, onOpenDemand }: EvaluationModuleProps) {
  const rows = policies.map((policy) => {
    const demandId = numberField(policy.summary_json, 'demand_id');
    const evaluationId = numberField(policy.summary_json, 'evaluation_id');
    const evaluation = evaluations.find((item) => item.id === evaluationId) || evaluations.find((item) => item.demand_id === demandId);
    return { policy, evaluation, plan: demandEvaluationPlanFromPolicy(policy, evaluation) };
  });
  const pendingCount = rows.filter(({ plan }) => ['pending', 'evaluating'].includes(plan.status)).length;
  const totalMargin = totalBy(rows, ({ plan }) => Number(plan.expectedGain || 0));
  const avgFeasibility = average(rows.map(({ plan }) => plan.attributions[0]?.beforeRatio || 0));

  return (
    <section className="wire-card strategy-module strategy-module-evaluation">
      <div className="strategy-module-head">
        <div>
          <div className="strategy-module-eyebrow">Evaluation</div>
          <div className="wire-card-title">{demandEvaluationStrategyLabel}</div>
        </div>
        <Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={onReload}>刷新</Button>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={onCreate}>生成</Button>
        </Space>
      </div>

      <div className="strategy-summary-grid">
        <div><span>待评估策略</span><strong>{numberText(pendingCount)}</strong></div>
        <div><span>平均可行性</span><strong>{percent(avgFeasibility)}</strong></div>
        <div><span>评估收益</span><strong>{money(totalMargin)}</strong></div>
      </div>

      <Table<(typeof rows)[number]>
        className="strategy-table strategy-demand-table"
        size="small"
        rowKey={({ policy }) => policy.id}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyState description={`暂无${demandEvaluationStrategyLabel}`} /> }}
        columns={[
          { title: '策略 ID', render: (_, { policy }) => <span className="strategy-code-cell">{stringField(policy.summary_json, 'demand_strategy_id', policy.policy_no)}</span> },
          { title: '关联需求 ID', render: (_, { policy }) => {
            const demandId = numberField(policy.summary_json, 'demand_id');
            return <Button size="small" type="link" disabled={!demandId} onClick={() => demandId && onOpenDemand(demandId)}>{demandId || '-'}</Button>;
          } },
          { title: '评估收益', render: (_, { plan }) => <span className="positive">+{money(plan.expectedGain)}</span> },
          { title: '可行性', render: (_, { plan }) => percent(plan.attributions[0]?.beforeRatio || 0) },
          { title: '状态', render: (_, { plan }) => <StatusTag value={plan.status} label={demandEvaluationStatusLabels[plan.status] || plan.status} /> },
          { title: '操作', render: (_, { policy, plan }) => (
            <Space size={4} wrap>
              <Button size="small" icon={<EyeOutlined />} onClick={() => onOpenPlan(plan, policy)}>详情</Button>
              <Button size="small" type="primary" icon={<CheckCircleOutlined />} disabled={!['pending', 'evaluating'].includes(plan.status)} onClick={() => onAcceptPlan(plan, policy)}>确认</Button>
              <Button size="small" danger icon={<StopOutlined />} disabled={plan.status === 'rejected' || plan.status === 'approved'} onClick={() => onRejectPlan(plan, policy)}>驳回</Button>
            </Space>
          ) },
        ]}
      />
    </section>
  );
}


function formatTpm(value: number) {
  return `${(value / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })}w`;
}

function findPlanPolicy(plan: StrategyPlan, policies: Policy[]) {
  return policies.find((item) => item.policy_no === plan.policyNo) || policies[0] || null;
}

interface WaveChartProps {
  item: StrategyAttribution;
}

function WaveChart({ item }: WaveChartProps) {
  const width = 320;
  const height = 150;
  const left = 38;
  const right = 10;
  const top = 12;
  const bottom = 22;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const points = item.series.map((demand, hour) => ({
    hour,
    demand,
    selfBefore: Math.min(demand, item.watermarkBefore),
    selfAfter: Math.min(demand, item.watermark),
  }));
  const maxY = Math.max(item.watermark, item.watermarkBefore, ...points.map((point) => point.demand)) * 1.08 || 1;
  const x = (hour: number) => left + (hour / 23) * plotWidth;
  const y = (value: number) => top + plotHeight - (value / maxY) * plotHeight;
  const beforeArea = `${points.map((point) => `${x(point.hour)},${y(point.selfBefore)}`).join(' ')} ${points.slice().reverse().map((point) => `${x(point.hour)},${y(0)}`).join(' ')}`;
  const afterArea = `${points.map((point) => `${x(point.hour)},${y(point.selfAfter)}`).join(' ')} ${points.slice().reverse().map((point) => `${x(point.hour)},${y(point.selfBefore)}`).join(' ')}`;
  const demandLine = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.hour)},${y(point.demand)}`).join('');
  const ticks = [0, Math.round(maxY / 2), Math.round(maxY)];

  return (
    <div className="strategy-wave-card">
      <div className="strategy-wave-head"><span><strong>{item.customer}</strong> <em>{item.model}</em></span><small>前 {formatTpm(item.watermarkBefore)} / 后 {formatTpm(item.watermark)}</small></div>
      <svg viewBox={`0 0 ${width} ${height}`}>
        {ticks.map((tick) => <g key={tick}><line x1={left} y1={y(tick)} x2={width - right} y2={y(tick)} /><text className="axis" x={left - 4} y={y(tick) + 3} textAnchor="end">{formatTpm(tick)}</text></g>)}
        <polygon points={beforeArea} className="wave-self-before-area" />
        <polygon points={afterArea} className="wave-self-after-area" />
        <path d={demandLine} className="wave-demand" />
        <polyline points={points.map((point) => `${x(point.hour)},${y(point.selfBefore)}`).join(' ')} className="wave-self-before-line" />
        <polyline points={points.map((point) => `${x(point.hour)},${y(point.selfAfter)}`).join(' ')} className="wave-self-line" />
        <line x1={left} y1={y(item.watermarkBefore)} x2={width - right} y2={y(item.watermarkBefore)} className="wave-watermark-before" />
        <line x1={left} y1={y(item.watermark)} x2={width - right} y2={y(item.watermark)} className="wave-watermark" />
        {[0, 6, 12, 18, 23].map((hour) => <text className="axis" key={hour} x={x(hour)} y={height - 6} textAnchor="middle">{hour}{hour === 23 ? 'h' : ''}</text>)}
      </svg>
    </div>
  );
}


interface FittingStrategyModuleProps {
  strategies: FittingStrategy[];
  onChange: (strategies: FittingStrategy[]) => void;
}

function FittingStrategyModule({ strategies, onChange }: FittingStrategyModuleProps) {
  const [editingStrategy, setEditingStrategy] = useState<FittingStrategy | null>(null);

  function saveStrategy(values: Pick<FittingStrategy, 'fittingAlgorithm' | 'manualParams'>) {
    if (!editingStrategy) return;
    onChange(strategies.map((item) => item.id === editingStrategy.id ? { ...item, ...values } : item));
    setEditingStrategy(null);
  }

  return (
    <section className="wire-card strategy-module strategy-module-fitting">
      <div className="strategy-module-head">
        <div>
          <div className="strategy-module-eyebrow">Fitting</div>
          <div className="wire-card-title">拟合策略</div>
        </div>
      </div>

      <div className="strategy-summary-grid strategy-summary-grid-2">
        <div><span>客户数</span><strong>{numberText(new Set(strategies.map((item) => item.customerName)).size)}</strong></div>
        <div><span>模型数</span><strong>{numberText(new Set(strategies.map((item) => item.modelName)).size)}</strong></div>
      </div>

      <Table<FittingStrategy>
        className="strategy-table strategy-fitting-table"
        size="small"
        rowKey="id"
        dataSource={strategies}
        pagination={false}
        scroll={{ x: 'max-content' }}
        columns={[
          { title: '客户名称', dataIndex: 'customerName' },
          { title: '模型名称', dataIndex: 'modelName', render: (value) => <span className="strategy-code-cell">{value}</span> },
          { title: '拟合算法', dataIndex: 'fittingAlgorithm', render: (value) => <span className="strategy-code-cell">{value}</span> },
          { title: '人工参数', dataIndex: 'manualParams', render: (value) => <span className="strategy-table-text">{value}</span> },
          { title: '操作', render: (_, record) => <Button size="small" icon={<EditOutlined />} onClick={() => setEditingStrategy(record)}>修改</Button> },
        ]}
      />

      <Modal title="修改拟合策略" open={!!editingStrategy} footer={null} destroyOnClose onCancel={() => setEditingStrategy(null)}>
        {editingStrategy ? (
          <Form key={editingStrategy.id} layout="vertical" initialValues={editingStrategy} onFinish={saveStrategy}>
            <Form.Item label="客户名称"><Input value={editingStrategy.customerName} disabled /></Form.Item>
            <Form.Item label="模型名称"><Input value={editingStrategy.modelName} disabled /></Form.Item>
            <Form.Item name="fittingAlgorithm" label="拟合算法" rules={[{ required: true, message: '请输入拟合算法' }]}><Input /></Form.Item>
            <Form.Item name="manualParams" label="人工参数"><Input.TextArea rows={4} /></Form.Item>
            <Button type="primary" htmlType="submit" block>保存</Button>
          </Form>
        ) : null}
      </Modal>
    </section>
  );
}


interface ScheduledTaskModuleProps {
  tasks: ScheduledTask[];
  onChange: (tasks: ScheduledTask[]) => void;
  onCreateTask?: (values: ScheduledTaskFormValues) => Promise<ScheduledTask | null>;
  onSaveTask?: (task: ScheduledTask, values: ScheduledTaskFormValues) => void;
}

function ScheduledTaskModule({ tasks, onChange, onCreateTask, onSaveTask }: ScheduledTaskModuleProps) {

  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [creatingTask, setCreatingTask] = useState(false);
  const activeCount = tasks.filter((task) => ['running', 'scheduled'].includes(task.status)).length;

  function saveTask(values: ScheduledTaskFormValues) {
    if (!editingTask) return;
    const payload = schedulePayload(values);
    const nextTask = {
      ...editingTask,
      taskName: values.taskName,
      status: values.status,
      triggerType: payload.trigger_type,
      cronExpr: payload.cron_expr,
      intervalSeconds: payload.interval_seconds,
      frequency: taskFrequency({ trigger_type: payload.trigger_type, cron_expr: payload.cron_expr, interval_seconds: payload.interval_seconds }),
      executeTime: taskExecuteTime({ trigger_type: payload.trigger_type, cron_expr: payload.cron_expr, interval_seconds: payload.interval_seconds, next_run_at: null }),
    };
    onChange(tasks.map((task) => task.id === editingTask.id ? nextTask : task));
    onSaveTask?.(nextTask, values);
    setEditingTask(null);
  }

  async function createTask(values: ScheduledTaskFormValues) {
    const nextTask = await onCreateTask?.(values);
    if (!nextTask) return;
    onChange([...tasks, nextTask]);
    setCreatingTask(false);
  }

  function deleteTask(id: string) {
    onChange(tasks.filter((task) => task.id !== id));
  }

  function renderExecuteTimeSelect() {
    return (
      <Form.Item noStyle shouldUpdate={(prev, current) => prev.frequencyKey !== current.frequencyKey}>
        {({ getFieldValue, setFieldsValue }) => {
          const frequencyKey = getFieldValue('frequencyKey') || 'daily';
          const options = taskExecuteTimeOptions[frequencyKey] || taskExecuteTimeOptions.daily;
          const currentValue = getFieldValue('executeTimeKey');
          if (!options.some((item) => item.value === currentValue)) {
            setTimeout(() => setFieldsValue({ executeTimeKey: options[0]?.value }), 0);
          }
          return (
            <Form.Item name="executeTimeKey" label="执行时间" rules={[{ required: true, message: '请选择执行时间' }]}>
              <Select options={options} />
            </Form.Item>
          );
        }}
      </Form.Item>
    );
  }

  return (
    <section className="wire-card strategy-module strategy-module-schedule">
      <div className="strategy-module-head">
        <div>
          <div className="strategy-module-eyebrow">Schedule</div>
          <div className="wire-card-title">定时任务管理</div>
        </div>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreatingTask(true)}>新增</Button>
      </div>

      <div className="strategy-summary-grid strategy-summary-grid-2">
        <div><span>任务总数</span><strong>{numberText(tasks.length)}</strong></div>
        <div><span>运行/待执行</span><strong>{numberText(activeCount)}</strong></div>
      </div>

      <div className="schedule-task-list">
        {tasks.map((task) => (
          <article className="schedule-task-card" key={task.id}>
            <div className="schedule-task-head">
              <strong>{task.taskName}</strong>
              <StatusTag value={task.status} label={scheduledTaskStatusLabels[task.status] || task.status} />
            </div>
            <div className="schedule-task-meta">
              <div><span>任务 ID</span><code>{task.algorithm}</code></div>
              <div><span>执行频率</span><b>{task.frequency}</b></div>
              <div><span>执行时间</span><b>{task.executeTime}</b></div>
            </div>
            <div className="schedule-task-actions">
              <Button size="small" icon={<EditOutlined />} onClick={() => setEditingTask(task)}>修改</Button>
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => deleteTask(task.id)}>删除</Button>
            </div>
          </article>
        ))}
        {!tasks.length ? <EmptyState description="暂无定时任务" /> : null}
      </div>

      <Modal title="新增定时任务" open={creatingTask} footer={null} destroyOnClose onCancel={() => setCreatingTask(false)}>
        <Form layout="vertical" initialValues={taskFormInitialValues()} onFinish={createTask}>
          <Form.Item name="taskName" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}><Input /></Form.Item>
          <Form.Item name="frequencyKey" label="执行频率" rules={[{ required: true, message: '请选择执行频率' }]}><Select options={taskFrequencyOptions.map(({ label, value }) => ({ label, value }))} /></Form.Item>
          {renderExecuteTimeSelect()}
          <Form.Item name="status" label="当前状态" rules={[{ required: true, message: '请选择当前状态' }]}>
            <Select options={Object.entries(scheduledTaskStatusLabels).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>确认新增</Button>
        </Form>
      </Modal>

      <Modal title="修改定时任务" open={!!editingTask} footer={null} destroyOnClose onCancel={() => setEditingTask(null)}>
        {editingTask ? (
          <Form key={editingTask.id} layout="vertical" initialValues={taskFormInitialValues(editingTask)} onFinish={saveTask}>
            <Form.Item name="taskName" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}><Input /></Form.Item>
            <Form.Item name="frequencyKey" label="执行频率" rules={[{ required: true, message: '请选择执行频率' }]}><Select options={taskFrequencyOptions.map(({ label, value }) => ({ label, value }))} /></Form.Item>
            {renderExecuteTimeSelect()}
            <Form.Item name="status" label="当前状态" rules={[{ required: true, message: '请选择当前状态' }]}>
              <Select options={Object.entries(scheduledTaskStatusLabels).map(([value, label]) => ({ value, label }))} />
            </Form.Item>
            <Button type="primary" htmlType="submit" block>保存</Button>
          </Form>
        ) : null}
      </Modal>
    </section>
  );
}



interface StrategyPolicyModuleProps {
  title: string;
  eyebrow: string;
  plans: StrategyPlan[];
  policies: Policy[];
  primaryLabel: string;
  primaryValue: number;
  onCreate: () => void;
  onOpenPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onAcceptPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onEditPlan: (plan: StrategyPlan, policy: Policy | null) => void;
  onAbandonPlan: (plan: StrategyPlan, policy: Policy | null) => void;
}

function StrategyPolicyModule({ title, eyebrow, plans, policies, primaryLabel, primaryValue, onCreate, onOpenPlan, onAcceptPlan, onEditPlan, onAbandonPlan }: StrategyPolicyModuleProps) {
  const acceptedCount = policies.filter((item) => item.status === 'accepted').length;
  const totalMachines = totalBy(plans, (plan) => totalBy(plan.flows, (flow) => flow.machines));

  return (
    <section className={`wire-card strategy-module strategy-module-${plans[0]?.kind || 'idle'}`}>
      <div className="strategy-module-head">
        <div>
          <div className="strategy-module-eyebrow">{eyebrow}</div>
          <div className="wire-card-title">{title}</div>
        </div>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={onCreate}>生成</Button>
      </div>

      <div className="strategy-summary-grid">
        <div><span>{primaryLabel}</span><strong>{money(primaryValue)}</strong></div>
        <div><span>腾挪机器</span><strong>{numberText(totalMachines)} 台</strong></div>
        <div><span>已确认策略</span><strong>{numberText(acceptedCount)}</strong></div>
      </div>

      <div className="strategy-plan-list">
        {plans.map((plan) => {
          const policy = findPlanPolicy(plan, policies);
          const status = policy?.status || plan.status;
          return (
            <article className="strategy-flow-plan" key={plan.id} role="button" tabIndex={0} onClick={() => onOpenPlan(plan, policy)} onKeyDown={(event) => { if (event.key === 'Enter') onOpenPlan(plan, policy); }}>
              <div className="strategy-flow-plan-head">
                <div>
                  <div className="strategy-policy-id">策略 ID：{policy?.policy_no || plan.policyNo}</div>
                </div>
                <div className="strategy-plan-gain"><span>预期收益</span><strong>+{money(plan.expectedGain)}/天</strong></div>
              </div>
              <div className="strategy-summary-grid strategy-summary-grid-2">
                <div><span>当前状态</span><strong><StatusTag value={status} /></strong></div>
                <div><span>生成时间</span><strong>{dateText(plan.generatedAt)}</strong></div>
              </div>
              <div className="strategy-plan-actions" onClick={(event) => event.stopPropagation()}>
                <Button size="small" icon={<EyeOutlined />} onClick={() => onOpenPlan(plan, policy)}>查看详情</Button>
                <Button size="small" type="primary" icon={<CheckCircleOutlined />} disabled={status !== 'draft'} onClick={() => onAcceptPlan(plan, policy)}>人工确认</Button>
                <Button size="small" danger icon={<StopOutlined />} disabled={status === 'cancelled'} onClick={() => onAbandonPlan(plan, policy)}>放弃</Button>
              </div>
            </article>
          );
        })}
        {!plans.length ? <EmptyState description="暂无策略方案" /> : null}
      </div>
    </section>
  );
}

interface StrategyPlanDetailProps {
  plan: StrategyPlan;
  policy: Policy | null;
  detail: PolicyDetail | null;
}

function StrategyPlanDetail({ plan, policy, detail }: StrategyPlanDetailProps) {
  const isDemandPlan = plan.kind === 'demand';
  const totalDailyGain = totalBy(plan.attributions, (item) => item.gain);

  return (
    <div className="strategy-report">

      <header className="strategy-report-head">
        <div>
          <h2>{plan.title}</h2>
          <p>{plan.detailLead}</p>
        </div>
        <StatusTag value={isDemandPlan ? plan.status : (policy?.status || plan.status)} label={isDemandPlan ? demandEvaluationStatusLabels[plan.status] : undefined} />

      </header>
      <div className="strategy-report-kpis">
        <div><span>策略 ID</span><strong>{policy?.policy_no || plan.policyNo}</strong></div>
        <div><span>{isDemandPlan ? '需求周期' : '策略窗口'}</span><strong>{plan.window}</strong></div>
        <div><span>{isDemandPlan ? '评估收益' : '预计收益'}</span><strong className="positive">+{money(plan.expectedGain)}{isDemandPlan ? '' : '/天'}</strong></div>
        <div><span>操作项</span><strong>{numberText(detail?.actions.length || plan.flows.length)}</strong></div>

      </div>

      <section className="strategy-report-section">
        <h3><span>1</span>{isDemandPlan ? '需求评估方案（需求 -> 策略）' : <>机器腾挪流向（源模型富余 {'->'} 目标模型紧缺）</>}</h3>

        {isDemandPlan ? (
          <div className="strategy-report-card">
            {plan.flows.map((flow) => (
              <div className="strategy-flow-row report" key={`${flow.source}-${flow.target}`}>
                <span className="strategy-flow-node"><b>{flow.source}</b><small>{flow.sourceModel} {flow.sourceRate}</small></span>
                <span className="strategy-flow-arrow">{'->'} {flow.machines}台 {'->'}</span>
                <span className="strategy-flow-node target"><b>{flow.target}</b><small>{flow.targetModel} {flow.targetRate}</small></span>
                <span className="strategy-flow-gain">+{money(flow.gain)}</span>
              </div>
            ))}
          </div>
        ) : (
          <Table<StrategyFlow>
            className="strategy-table strategy-report-table"
            size="small"
            rowKey={(record, index) => `${record.source}-${record.target}-${record.machines}-${index}`}
            dataSource={plan.flows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '源集群', dataIndex: 'source' },
              { title: '源模型', dataIndex: 'sourceModel', render: (value, record) => <span className="strategy-code-cell">{value} {record.sourceRate}</span> },
              { title: '源机器台数', render: (_, record) => `${record.sourceMachinesBefore} -> ${record.sourceMachinesAfter} 台` },
              { title: '源利用率变化', render: (_, record) => `${ratioPercent(record.sourceUtilizationBefore)} -> ${ratioPercent(record.sourceUtilizationAfter)}` },
              { title: '接受集群', dataIndex: 'target' },
              { title: '接受模型', dataIndex: 'targetModel', render: (value, record) => <span className="strategy-code-cell">{value} {record.targetRate}</span> },
              { title: '接受机器台数', render: (_, record) => `${record.targetMachinesBefore} -> ${record.targetMachinesAfter} 台` },
              { title: '接受利用率变化', render: (_, record) => `${ratioPercent(record.targetUtilizationBefore)} -> ${ratioPercent(record.targetUtilizationAfter)}` },
              { title: '腾挪机器', dataIndex: 'machines', render: (value) => `${value} 台` },
              { title: '收益', dataIndex: 'gain', render: (value) => <span className="positive">+{money(value)}/天</span> },
            ]}
          />
        )}
      </section>

      <section className="strategy-report-section">
        <h3><span>2</span>{isDemandPlan ? '需求收益核算' : '逐调整收益核算'}</h3>
        <div className="strategy-formula">
          {isDemandPlan ? (
            '评估收益 = 预计收入 - 预计成本；可行性与客户价值作为人工确认依据，确认或驳回会同步需求看板状态。'
          ) : (
            <>
              <p>delta自建增加调用量 = 调整后水位 - 调整前水位；边际收入 = 本次水位调整带来的单客户收益贡献；单日调整收益总和 = {money(totalDailyGain)}/天。</p>
              <p>调整前水位表示当前自建承接上限，调整后水位表示策略给该客户模型设置的新自建承接上限，delta为本次预计新增自建承接量。</p>
              <p>面积按逐时自建承接量求和：每小时取 min(客户实跑, 水位线)，分别计算调整前面积、调整后面积和面积变化。</p>
              <p>「优先级」按百万token单价降序，与求解器承接排序一致：单价越高越优先承接自建。</p>
            </>
          )}
        </div>

        <Table<StrategyAttribution>
          className="strategy-table strategy-report-table"
          size="small"
          rowKey={(record) => `${record.uid}-${record.model}`}
          dataSource={plan.attributions}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '优先级', render: (_v, _r, index) => index + 1, width: 64 },
            { title: '客户名称', dataIndex: 'customerName' },
            { title: 'uid', dataIndex: 'uid' },
            { title: '模型名称', dataIndex: 'model' },
            { title: '百万token单价（元）', dataIndex: 'pricePerMillionTokens', render: (value) => Number(value).toFixed(2) },
            { title: '边际收入（元/天）', dataIndex: 'marginalRevenue', render: (value) => <span className={Number(value) >= 0 ? 'positive' : undefined}>{Number(value) >= 0 ? '+' : ''}{money(value)}</span> },
            { title: '调整前水位（万TPM）', dataIndex: 'beforeVolume', render: numberText },
            { title: '调整后水位（万TPM）', dataIndex: 'afterVolume', render: numberText },
            { title: 'delta自建增加调用量（万TPM）', dataIndex: 'deltaVolume', render: (value) => <span className={Number(value) >= 0 ? 'positive' : undefined}>{Number(value) >= 0 ? '+' : ''}{numberText(value)}</span> },
            ...(!isDemandPlan ? [
              { title: '调整前面积（万TPM·h）', dataIndex: 'beforeArea', render: numberText },
              { title: '调整后面积（万TPM·h）', dataIndex: 'afterArea', render: numberText },
              { title: '面积变化（万TPM·h）', dataIndex: 'deltaArea', render: (value: number) => <span className={Number(value) >= 0 ? 'positive' : undefined}>{Number(value) >= 0 ? '+' : ''}{numberText(value)}</span> },
            ] : []),
            { title: '单tpm收入（元/TPM）', dataIndex: 'density', render: (value) => Number(value).toFixed(4) },
          ]}
        />
      </section>

      <section className="strategy-report-section">
        <h3><span>3</span>{isDemandPlan ? '需求预测波形 x 可承接水位' : '客户实跑波形 x 切量水位线'}</h3>

        <div className="strategy-wave-legend"><span className="self-before"></span>调整前自建承接量<span className="self"></span>调整后自建承接量<span className="demand"></span>客户实跑波形<span className="watermark-before"></span>调整前水位线<span className="watermark"></span>调整后水位线</div>
        <div className="strategy-wave-grid">{plan.attributions.map((item) => <WaveChart item={item} key={`${item.customer}-${item.model}`} />)}</div>
      </section>
    </div>
  );
}



export function StrategyDashboard() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const [createOpen, setCreateOpen] = useState(false);

  const [createTemplate, setCreateTemplate] = useState<StrategyTemplateKey>('demand_evaluation');
  const [selected, setSelected] = useState<Policy | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<StrategyPlan | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [taskRows, setTaskRows] = useState<ScheduledTask[]>([]);
  const [fittingStrategies, setFittingStrategies] = useState<FittingStrategy[]>([]);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const demandPolicyList = useAsync(() => policiesApi.list({ page: 1, page_size: 50, algorithm: 'demand_evaluation' }), []);
  const evaluations = useAsync(() => evaluationsApi.list({ page: 1, page_size: 50 }), []);
  const jobs = useAsync(() => jobsApi.list(), []);
  const fittingConfigs = useAsync(() => fittingsApi.configs(), []);

  const policyItems = useMemo(() => policies.data?.items || [], [policies.data?.items]);

  const demandPolicyItems = useMemo(() => demandPolicyList.data?.items || [], [demandPolicyList.data?.items]);
  const evaluationItems = useMemo(() => evaluations.data?.items || [], [evaluations.data?.items]);
  const demandPolicies = useMemo(() => demandPolicyItems.filter(isDemandEvaluationPolicy), [demandPolicyItems]);
  const idlePolicies = useMemo(() => policyItems.filter((item) => !isDemandEvaluationPolicy(item) && isIdlePolicy(item)), [policyItems]);
  const busyPolicies = useMemo(() => policyItems.filter((item) => !isDemandEvaluationPolicy(item) && isBusyPolicy(item)), [policyItems]);
  const idlePlans = useMemo(() => idlePolicies.map((policy) => timePeriodPlanFromPolicy(policy, 'idle')), [idlePolicies]);
  const busyPlans = useMemo(() => busyPolicies.map((policy) => timePeriodPlanFromPolicy(policy, 'busy')), [busyPolicies]);

  const idleGain = totalBy(idlePolicies, (item) => Number(item.expected_off_peak_gain || item.expected_revenue_gain || 0));
  const busyGain = totalBy(busyPolicies, (item) => Number(item.expected_revenue_gain || 0));
  const loading = policies.loading || demandPolicyList.loading || evaluations.loading || jobs.loading || fittingConfigs.loading;
  const error = policies.error || demandPolicyList.error || evaluations.error || jobs.error || fittingConfigs.error;


  useEffect(() => {
    setTaskRows((jobs.data || []).map(scheduledTaskFromJob));
  }, [jobs.data]);

  useEffect(() => {
    setFittingStrategies(uniqueFittingStrategies(fittingConfigs.data || []));
  }, [fittingConfigs.data]);

  useEffect(() => {
    const demandId = Number(params.get('demand_id') || 0);

    if (!demandId || demandPolicyList.loading || selectedPlan) return;
    const policy = demandPolicies.find((item) => numberField(item.summary_json, 'demand_id') === demandId);
    if (!policy) return;
    const evaluationId = numberField(policy.summary_json, 'evaluation_id');
    const evaluation = evaluationItems.find((item) => item.id === evaluationId) || evaluationItems.find((item) => item.demand_id === demandId);
    void openPlanDetail(demandEvaluationPlanFromPolicy(policy, evaluation), policy);
    setParams({}, { replace: true });
  }, [params, setParams, demandPolicyList.loading, demandPolicies, evaluationItems, selectedPlan]);

  function openCreate(template: StrategyTemplateKey) {

    setCreateTemplate(template);
    setCreateOpen(true);
  }

  async function createRun(values: { template: StrategyTemplateKey }) {
    const selectedTemplate = strategyTemplateOptions.find((item) => item.value === values.template) || strategyTemplateOptions[0];
    const pendingDemandIds = evaluationItems
      .filter((item) => ['draft', 'pending'].includes(item.status))
      .map((item) => item.demand_id);
    setSubmitting(true);
    try {
      await policiesApi.createRun({
        algorithm: selectedTemplate.algorithm,
        demand_ids: selectedTemplate.value === 'demand_evaluation' ? pendingDemandIds : undefined,
        params: { template: selectedTemplate.label, module: selectedTemplate.value },
      });
      message.success(`${selectedTemplate.label}生成已提交`);
      setCreateOpen(false);
      await policies.reload();
      await demandPolicyList.reload();
      await evaluations.reload();

    } finally {
      setSubmitting(false);
    }
  }


  function resolvePlanPolicy(plan: StrategyPlan, policy: Policy | null) {
    if (policy) return policy;
    if (plan.kind === 'demand') return demandPolicies.find((item) => item.policy_no === plan.policyNo) || null;
    return findPlanPolicy(plan, plan.kind === 'idle' ? idlePolicies : busyPolicies);
  }


  async function openPlanDetail(plan: StrategyPlan, policy: Policy | null) {
    const targetPolicy = resolvePlanPolicy(plan, policy);
    setSelectedPlan(plan);
    setSelected(targetPolicy);
    setDetail(targetPolicy ? await policiesApi.detail(targetPolicy.id) : null);
  }

  async function acceptPlan(plan: StrategyPlan, policy: Policy | null) {
    const targetPolicy = resolvePlanPolicy(plan, policy);
    if (!targetPolicy) {
      message.warning('未找到可确认的策略记录');
      return;
    }
    await policiesApi.accept(targetPolicy.id, { operator: 'frontend', comment: plan.kind === 'demand' ? '需求评估方案确认' : undefined });
    message.success(plan.kind === 'demand' ? '需求评估方案已确认' : '策略已人工确认');
    await policies.reload();
    await demandPolicyList.reload();
    await evaluations.reload();
    if (selectedPlan?.id === plan.id) await openPlanDetail(plan, targetPolicy);

  }


  function editPlan(plan: StrategyPlan, policy: Policy | null) {
    const targetPolicy = resolvePlanPolicy(plan, policy);
    if (!targetPolicy) {
      message.warning('未找到可修改的策略记录');
      return;
    }
    if (plan.kind === 'demand') {
      message.warning('需求评估方案不支持在此修改机器台数和水位线');
      return;
    }
    if (targetPolicy.status === 'accepted') {
      message.warning('策略已人工确认，不能再修改');
      return;
    }
    setSelectedPlan(plan);
    setSelected(targetPolicy);
    void policiesApi.detail(targetPolicy.id).then(setDetail);
    setEditOpen(true);
  }

  async function abandonPlan(plan: StrategyPlan, policy: Policy | null) {
    const targetPolicy = resolvePlanPolicy(plan, policy);
    if (!targetPolicy) {
      message.warning('未找到可放弃的策略记录');
      return;
    }
    const reason = plan.kind === 'demand' ? '需求评估方案驳回' : '前端放弃策略方案';
    await policiesApi.cancel(targetPolicy.id, { operator: 'frontend', reason });
    message.success(plan.kind === 'demand' ? '需求评估方案已驳回' : '策略方案已放弃');
    setSelected(null);
    setSelectedPlan(null);
    setDetail(null);
    await policies.reload();
    await demandPolicyList.reload();
    await evaluations.reload();
  }



  async function createScheduledTask(values: ScheduledTaskFormValues) {
    try {
      const payload = schedulePayload(values);
      const created = await jobsApi.create({
        description: values.taskName,
        trigger_type: payload.trigger_type,
        cron_expr: payload.cron_expr,
        interval_seconds: payload.interval_seconds,
        enabled: values.status !== 'paused',
      });
      message.success('定时任务已新增');
      await jobs.reload();
      return scheduledTaskFromJob(created);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '定时任务新增失败');
      return null;
    }
  }

  async function saveScheduledTask(task: ScheduledTask, values: ScheduledTaskFormValues) {
    try {
      const payload = schedulePayload(values);
      await jobsApi.patch(task.id, {
        description: values.taskName,
        trigger_type: payload.trigger_type,
        cron_expr: payload.cron_expr,
        interval_seconds: payload.interval_seconds,
        enabled: values.status !== 'paused',
      });
      message.success('定时任务已保存');
      await jobs.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '定时任务保存失败');
    }
  }

  async function patch(values: StrategyEditFormValues) {
    if (!selected || !selectedPlan) return;
    if (selected.status === 'accepted') {
      message.warning('策略已人工确认，不能再修改');
      setEditOpen(false);
      return;
    }
    setSubmitting(true);
    try {
      const patched = await policiesApi.patch(selected.id, {
        summary_json: applyStrategyEdits(selected, values),
      });
      message.success('策略已修改');
      setEditOpen(false);
      await policies.reload();
      await demandPolicyList.reload();
      await openPlanDetail(timePeriodPlanFromPolicy(patched, selectedPlan.kind === 'busy' ? 'busy' : 'idle'), patched);

    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Strategies"
        title="策略看板"
        description="聚合需求评估、闲时和忙时三类策略，统一查看收益、状态与执行建议。"
        actions={<Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate('demand_evaluation')}>策略生成</Button>}
      />
      {error ? <ErrorState error={error} onRetry={() => { void policies.reload(); void demandPolicyList.reload(); void evaluations.reload(); void jobs.reload(); void fittingConfigs.reload(); }} /> : null}


      <Spin spinning={loading}>
        <div className="strategy-dashboard-grid page-section">
          <EvaluationModule evaluations={evaluationItems} policies={demandPolicies} onCreate={() => openCreate('demand_evaluation')} onReload={() => { void policies.reload(); void demandPolicyList.reload(); void evaluations.reload(); }} onOpenPlan={openPlanDetail} onAcceptPlan={acceptPlan} onRejectPlan={abandonPlan} onOpenDemand={(demandId) => navigate(`/demands/${demandId}`)} />

          <FittingStrategyModule strategies={fittingStrategies} onChange={setFittingStrategies} />
          <ScheduledTaskModule tasks={taskRows} onChange={setTaskRows} onCreateTask={createScheduledTask} onSaveTask={saveScheduledTask} />

          <StrategyPolicyModule title="闲时策略" eyebrow="Idle" plans={idlePlans} policies={idlePolicies} primaryLabel="低峰收益" primaryValue={idleGain || totalBy(idlePlans, (plan) => plan.expectedGain)} onCreate={() => openCreate('idle')} onOpenPlan={openPlanDetail} onAcceptPlan={acceptPlan} onEditPlan={editPlan} onAbandonPlan={abandonPlan} />
          <StrategyPolicyModule title="忙时策略" eyebrow="Busy" plans={busyPlans} policies={busyPolicies} primaryLabel="忙时收益" primaryValue={busyGain || totalBy(busyPlans, (plan) => plan.expectedGain)} onCreate={() => openCreate('busy')} onOpenPlan={openPlanDetail} onAcceptPlan={acceptPlan} onEditPlan={editPlan} onAbandonPlan={abandonPlan} />
        </div>
      </Spin>

      <Modal title="策略生成" open={createOpen} footer={null} onCancel={() => setCreateOpen(false)}>
        <Form key={createTemplate} layout="vertical" onFinish={createRun} initialValues={{ template: createTemplate }}>
          <Form.Item name="template" label="策略模板" rules={[{ required: true }]}><Select options={strategyTemplateOptions} /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>生成</Button>
        </Form>
      </Modal>
      <Drawer title="方案详情" rootClassName="strategy-detail-drawer" open={!!selectedPlan} onClose={() => { setSelected(null); setSelectedPlan(null); setDetail(null); }} width={980}>

        {selectedPlan && <Space className="strategy-detail-actions"><Button icon={<EditOutlined />} disabled={selectedPlan.kind === 'demand' || (selected?.status || selectedPlan.status) === 'accepted'} onClick={() => editPlan(selectedPlan, selected)}>修改</Button><Button type="primary" icon={<CheckCircleOutlined />} disabled={selectedPlan.kind === 'demand' ? !['pending', 'evaluating'].includes(selectedPlan.status) : (selected?.status || selectedPlan.status) !== 'draft'} onClick={() => acceptPlan(selectedPlan, selected)}>{selectedPlan.kind === 'demand' ? '确认' : '人工确认'}</Button><Button danger icon={<StopOutlined />} disabled={selectedPlan.kind === 'demand' ? ['approved', 'rejected'].includes(selectedPlan.status) : (selected?.status || selectedPlan.status) === 'cancelled'} onClick={() => abandonPlan(selectedPlan, selected)}>{selectedPlan.kind === 'demand' ? '驳回' : '放弃'}</Button></Space>}

        {selectedPlan ? <StrategyPlanDetail plan={selectedPlan} policy={selected} detail={detail} /> : null}
      </Drawer>
      <Modal title="修改策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)} width={760}>
        {selectedPlan ? (
          <Form key={selectedPlan.id} layout="vertical" onFinish={patch} initialValues={strategyEditInitialValues(selectedPlan)}>
            {selectedPlan.flows.length ? (
              <section className="strategy-edit-section">
                <h3>机器腾挪台数</h3>
                {selectedPlan.flows.map((flow, index) => (
                  <div className="strategy-edit-row" key={`${flow.source}-${flow.target}-${index}`}>
                    <div><strong>{flow.source} {'->'} {flow.target}</strong><small>{flow.sourceModel} {'->'} {flow.targetModel}</small></div>
                    <Form.Item name={['flows', index, 'machines']} rules={[{ required: true, message: '请输入腾挪台数' }]}>
                      <InputNumber min={0} precision={0} addonAfter="台" />
                    </Form.Item>
                  </div>
                ))}
              </section>
            ) : null}
            {selectedPlan.attributions.length ? (
              <section className="strategy-edit-section">
                <h3>切量水位线</h3>
                {selectedPlan.attributions.map((item, index) => (
                  <div className="strategy-edit-row" key={`${item.customer}-${item.model}-${index}`}>
                    <div><strong>{item.customer}</strong><small>{item.model} 当前 {numberText(item.beforeVolume)} 万TPM</small></div>
                    <Form.Item name={['attributions', index, 'watermark']} rules={[{ required: true, message: '请输入切量水位线' }]}>
                      <InputNumber min={0} precision={2} addonAfter="万TPM" />
                    </Form.Item>
                  </div>
                ))}
              </section>
            ) : null}
            <Button loading={submitting} type="primary" htmlType="submit" block>保存修改</Button>
          </Form>
        ) : null}
      </Modal>
    </>
  );
}
