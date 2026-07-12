import { Button, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
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
import { money, numberText, percent } from '../../utils/format';

import { parseJsonObject } from '../../utils/json';

type StrategyTemplateKey = 'demand_evaluation' | 'idle' | 'busy';

const strategyTemplateOptions: Array<{ label: string; value: StrategyTemplateKey; algorithm: string }> = [
  { label: '需求评估策略', value: 'demand_evaluation', algorithm: 'demand_evaluation' },
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
  model: string;
  density: number;
  beforeRatio: number;
  afterRatio: number;
  watermarkBefore: number;
  watermark: number;
  beforeVolume: number;
  afterVolume: number;
  deltaVolume: number;
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
}

const scheduledTaskStatusLabels: Record<string, string> = {
  running: '运行中',
  scheduled: '待执行',
  paused: '已暂停',
  failed: '异常',
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

function taskFrequency(schedule: JobSchedule) {
  if (schedule.trigger_type === 'interval' && schedule.interval_seconds) return `每 ${Math.round(schedule.interval_seconds / 60)} 分钟`;
  if (schedule.trigger_type === 'cron' && schedule.cron_expr) return 'Cron';
  return schedule.trigger_type;
}

function taskExecuteTime(schedule: JobSchedule) {
  return schedule.next_run_at || schedule.cron_expr || (schedule.interval_seconds ? `${schedule.interval_seconds}s` : '-');
}

function scheduledTaskFromJob(schedule: JobSchedule): ScheduledTask {
  return {
    id: schedule.job_name,
    taskName: schedule.description || schedule.job_name,
    algorithm: schedule.job_name,
    frequency: taskFrequency(schedule),
    executeTime: taskExecuteTime(schedule),
    status: taskStatus(schedule),
  };
}

function fittingStrategyFromConfig(config: FittingConfig): FittingStrategy {
  return {
    id: String(config.id),
    customerName: config.customer_code,
    modelName: config.model_name,
    fittingAlgorithm: config.algo_name,
    manualParams: JSON.stringify(config.params_json || {}),
  };
}


function isIdlePolicy(policy: Policy) {
  const text = policyText(policy);
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return policy.algorithm === 'off_peak' || module === 'idle' || ['闲时策略', '闲忙时策略'].includes(template) || text.includes('闲时');
}

function isBusyPolicy(policy: Policy) {
  const text = policyText(policy);
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return module === 'busy' || template === '忙时策略' || (policy.algorithm === 'time_period' && !isIdlePolicy(policy)) || (text.includes('忙时') && !isIdlePolicy(policy));
}

function isDemandEvaluationPolicy(policy: Policy) {
  const template = summaryField(policy, 'template');
  const module = summaryField(policy, 'module');
  return policy.algorithm === 'demand_evaluation' || module === 'demand_evaluation' || template === '需求评估策略';
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
    sourceUtilizationBefore: 0,
    sourceUtilizationAfter: 0,
    target,
    targetModel: stringField(move, 'model', stringField(move, 'to_model', '-')),
    targetRate: `${formatTpm(numberField(move, 'to_tpm_per_machine'))}/台`,
    targetMachinesBefore,
    targetMachinesAfter,
    targetUtilizationBefore: 0,
    targetUtilizationAfter: 0,
    machines: numberField(move, 'machine_count', 1),
    gain: numberField(move, 'gain_yuan_day', numberField(move, 'gain', Number(policy.expected_revenue_gain || 0) / Math.max(index + 1, 1))),
  };
}

function attributionFromWatermark(row: Record<string, unknown>, policy: Policy, index: number): StrategyAttribution {
  const before = numberField(row, 'watermark_before', numberField(row, 'before_watermark'));
  const after = numberField(row, 'watermark_after', numberField(row, 'watermark', before));
  const delta = numberField(row, 'delta', after - before);
  const gain = numberField(row, 'gain_yuan_day', Number(policy.expected_revenue_gain || 0) / Math.max(index + 1, 1));
  const base = Math.max(before, after, 1);
  return {
    customer: stringField(row, 'customer', stringField(row, 'customer_code', stringField(row, 'report_id', '-'))),
    model: stringField(row, 'model', stringField(row, 'model_name', '-')),
    density: delta ? gain / Math.abs(delta) : 0,
    beforeRatio: before / base,
    afterRatio: after / base,
    watermarkBefore: before,
    watermark: after,
    beforeVolume: before / 10000,
    afterVolume: after / 10000,
    deltaVolume: delta / 10000,
    gain,
    fallback: stringField(row, 'fallback', stringField(row, 'reason', '-')),
    series: Array.from({ length: 24 }, () => Math.max(before, after)),
  };
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
  const moves = [...arrayField(summary, 'node_moves'), ...arrayField(rb, 'moves')];
  const watermarkChanges = [...arrayField(summary, 'watermark_changes'), ...arrayField(rb, 'customer_watermark_delta'), ...arrayField(summary, 'accepted_customers')];
  const expectedGain = kind === 'idle' ? Number(policy.expected_off_peak_gain || policy.expected_revenue_gain || 0) : Number(policy.expected_revenue_gain || 0);
  return {
    id: `${kind}-${policy.id}`,
    kind,
    title: stringField(summary, 'title', kind === 'idle' ? '闲时策略方案' : '忙时策略方案'),
    subtitle: stringField(summary, 'description', stringField(summary, 'reason', '')),
    policyNo: policy.policy_no,
    window: stringField(summary, 'window', kind === 'idle' ? '闲时窗口' : '忙时窗口'),
    expectedGain,
    status: policy.status,
    flows: moves.map((move, index) => flowFromMove(move, policy, index)),
    attributions: watermarkChanges.map((row, index) => attributionFromWatermark(row, policy, index)),
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
    expectedGain,
    status,
    flows: [
      { source: '需求报备', sourceModel: reportId, sourceRate: `${formatTpm(tpm)} TPM`, sourceMachinesBefore: 0, sourceMachinesAfter: Math.max(1, Math.ceil(tpm / 100000)), machines: Math.max(1, Math.ceil(tpm / 100000)), target: '需求评估策略', targetModel: actionPayload.model, targetRate: `可行性 ${percent(feasibility)}`, targetMachinesBefore: 0, targetMachinesAfter: Math.max(1, Math.ceil(tpm / 100000)), sourceUtilizationBefore: feasibility, sourceUtilizationAfter: benefit, targetUtilizationBefore: feasibility, targetUtilizationAfter: benefit, gain: expectedGain },
    ],
    attributions: [
      { customer: reportId, model: actionPayload.model, density: benefit, beforeRatio: feasibility, afterRatio: benefit, watermarkBefore: Math.round(tpm * feasibility), watermark: tpm, beforeVolume: Number(actionPayload.expected_cost || 0), afterVolume: Number(actionPayload.expected_revenue || 0), deltaVolume: expectedGain, gain: expectedGain, fallback: actionPayload.recommendation, series: Array.from({ length: 24 }, (_, hour) => Math.round(tpm * (0.68 + Math.sin((hour / 24) * Math.PI) * 0.28 + (hour % 5) * 0.015))) },
    ],
    utilRows: [
      { cluster: '需求评估', model: actionPayload.model, capacityBefore: money(actionPayload.expected_cost), capacityAfter: money(actionPayload.expected_revenue), utilizationBefore: feasibility, utilizationAfter: benefit },
    ],
    detailLead: '需求评估策略以需求报备、可行性和收益测算为输入。人工确认后需求看板状态变为确认，驳回后同步变为驳回。',
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
          <div className="wire-card-title">需求评估策略</div>
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
        locale={{ emptyText: <EmptyState description="暂无需求评估策略" /> }}
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
  onSaveTask?: (task: ScheduledTask) => void;
}

function ScheduledTaskModule({ tasks, onChange, onSaveTask }: ScheduledTaskModuleProps) {

  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const runningCount = tasks.filter((task) => task.status === 'running').length;
  const nextTask = tasks.find((task) => task.status === 'scheduled') || tasks[0];

  function saveTask(values: Omit<ScheduledTask, 'id'>) {
    if (!editingTask) return;
    const nextTask = { ...editingTask, ...values };
    onChange(tasks.map((task) => task.id === editingTask.id ? nextTask : task));
    onSaveTask?.(nextTask);
    setEditingTask(null);
  }


  function addTask() {
    onChange([
      ...tasks,
      { id: `task-manual-${Date.now()}`, taskName: '人工新增任务', algorithm: 'time_period', frequency: '每日', executeTime: '00:00', status: 'scheduled' },
    ]);
  }

  function deleteTask(id: string) {
    onChange(tasks.filter((task) => task.id !== id));
  }

  return (
    <section className="wire-card strategy-module strategy-module-schedule">
      <div className="strategy-module-head">
        <div>
          <div className="strategy-module-eyebrow">Schedule</div>
          <div className="wire-card-title">定时任务管理</div>
        </div>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={addTask}>新增</Button>
      </div>

      <div className="strategy-summary-grid">
        <div><span>任务总数</span><strong>{numberText(tasks.length)}</strong></div>
        <div><span>运行中</span><strong>{numberText(runningCount)}</strong></div>
        <div><span>下一次执行</span><strong>{nextTask?.executeTime || '-'}</strong></div>
      </div>

      <Table<ScheduledTask>
        className="strategy-table strategy-schedule-table"
        size="small"
        rowKey="id"
        dataSource={tasks}
        pagination={false}
        scroll={{ x: 'max-content' }}
        columns={[
          { title: '任务名称', dataIndex: 'taskName', render: (value) => <span className="strategy-table-text">{value}</span> },
          { title: '算法', dataIndex: 'algorithm', render: (value) => <span className="strategy-code-cell">{value}</span> },
          { title: '执行频率', dataIndex: 'frequency', render: (value) => <span className="strategy-table-text">{value}</span> },
          { title: '执行时间', dataIndex: 'executeTime', render: (value) => <span className="strategy-code-cell">{value}</span> },
          { title: '当前状态', dataIndex: 'status', render: (value) => <StatusTag value={value} label={scheduledTaskStatusLabels[value] || value} /> },
          { title: '操作', render: (_, record) => <Space><Button size="small" icon={<EditOutlined />} onClick={() => setEditingTask(record)}>修改</Button><Button size="small" danger icon={<DeleteOutlined />} onClick={() => deleteTask(record.id)}>删除</Button></Space> },
        ]}
      />

      <Modal title="修改定时任务" open={!!editingTask} footer={null} destroyOnClose onCancel={() => setEditingTask(null)}>
        {editingTask ? (
          <Form key={editingTask.id} layout="vertical" initialValues={editingTask} onFinish={saveTask}>
            <Form.Item name="taskName" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}><Input /></Form.Item>
            <Form.Item name="algorithm" label="算法" rules={[{ required: true, message: '请输入算法' }]}><Input /></Form.Item>
            <Form.Item name="frequency" label="执行频率" rules={[{ required: true, message: '请输入执行频率' }]}><Input /></Form.Item>
            <Form.Item name="executeTime" label="执行时间" rules={[{ required: true, message: '请输入执行时间' }]}><Input /></Form.Item>
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
            <article className="strategy-flow-plan" key={plan.id}>
              <div className="strategy-flow-plan-head">
                <div>
                  <div className="strategy-policy-id">策略 ID：{policy?.policy_no || plan.policyNo}</div>
                  <h3>{plan.title}</h3>
                  <p>{plan.subtitle}</p>
                </div>
                <div className="strategy-plan-gain"><span>预计收益</span><strong>+{money(plan.expectedGain)}/天</strong><StatusTag value={status} /></div>
              </div>
              <div className="strategy-flow-list">
                {plan.flows.map((flow) => (
                  <div className="strategy-flow-row" key={`${flow.source}-${flow.target}`}>
                    <span className="strategy-flow-node"><b>{flow.source}</b><small>{flow.sourceModel} {flow.sourceRate}</small></span>
                    <span className="strategy-flow-arrow">{'->'} {flow.machines}台 {'->'}</span>
                    <span className="strategy-flow-node target"><b>{flow.target}</b><small>{flow.targetModel} {flow.targetRate}</small></span>
                    <span className="strategy-flow-gain">+{money(flow.gain)}{plan.kind === 'demand' ? '' : '/天'}</span>

                  </div>
                ))}
              </div>
              <div className="strategy-plan-actions">
                <Button size="small" icon={<EyeOutlined />} onClick={() => onOpenPlan(plan, policy)}>详情</Button>
                <Button size="small" type="primary" icon={<CheckCircleOutlined />} disabled={status !== 'draft'} onClick={() => onAcceptPlan(plan, policy)}>人工确认</Button>
                <Button size="small" icon={<EditOutlined />} onClick={() => onEditPlan(plan, policy)}>修改</Button>
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
            rowKey={(record) => `${record.source}-${record.target}-${record.machines}`}
            dataSource={plan.flows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '源集群', dataIndex: 'source' },
              { title: '源模型', dataIndex: 'sourceModel', render: (value, record) => <span className="strategy-code-cell">{value} {record.sourceRate}</span> },
              { title: '源机器台数', render: (_, record) => `${record.sourceMachinesBefore} -> ${record.sourceMachinesAfter} 台` },
              { title: '源利用率变化', render: (_, record) => `${percent(record.sourceUtilizationBefore)} -> ${percent(record.sourceUtilizationAfter)}` },
              { title: '接受集群', dataIndex: 'target' },
              { title: '接受模型', dataIndex: 'targetModel', render: (value, record) => <span className="strategy-code-cell">{value} {record.targetRate}</span> },
              { title: '接受机器台数', render: (_, record) => `${record.targetMachinesBefore} -> ${record.targetMachinesAfter} 台` },
              { title: '接受利用率变化', render: (_, record) => `${percent(record.targetUtilizationBefore)} -> ${percent(record.targetUtilizationAfter)}` },
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
              <p>单日调整收益总和 = {plan.attributions.map((item) => money(item.gain)).join(' + ')} = {money(totalDailyGain)}/天。</p>
              <ul className="strategy-formula-list">
                {plan.attributions.map((item) => (
                  <li key={`${item.customer}-${item.model}`}>{item.customer} / {item.model}：单TPM收入 {item.density.toFixed(4)} 元/TPM x delta自建增加调用量 {numberText(item.deltaVolume)} 万TPM x 10,000 = {money(item.gain)}/天；调整前自建水位 {numberText(item.beforeVolume)} 万TPM，调整后自建水位 {numberText(item.afterVolume)} 万TPM。</li>
                ))}
              </ul>
            </>
          )}
        </div>

        <Table<StrategyAttribution>
          className="strategy-table strategy-report-table"
          size="small"
          rowKey={(record) => `${record.customer}-${record.model}`}
          dataSource={plan.attributions}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '客户名称', dataIndex: 'customer' },
            { title: '模型名称', dataIndex: 'model' },
            { title: '单TPM收入（元/TPM）', dataIndex: 'density', render: (value) => Number(value).toFixed(4) },
            { title: '调整前自建水位（万TPM）', dataIndex: 'beforeVolume', render: numberText },
            { title: '调整后自建水位（万TPM）', dataIndex: 'afterVolume', render: numberText },
            { title: 'delta自建增加调用量（万TPM）', dataIndex: 'deltaVolume', render: (value) => <span className="positive">+{numberText(value)}</span> },
            { title: '收益（元/天）', dataIndex: 'gain', render: (value) => <span className="positive">+{money(value)}</span> },
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
    setFittingStrategies((fittingConfigs.data || []).map(fittingStrategyFromConfig));
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



  async function saveScheduledTask(task: ScheduledTask) {
    try {
      await jobsApi.patch(task.id, { enabled: task.status !== 'paused' });
      message.success('定时任务已保存');
      await jobs.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '定时任务保存失败');
    }
  }

  async function patch(values: { summary_json?: string; constraints_json?: string; expected_revenue_gain?: string; effective_from?: string; effective_to?: string }) {

    if (!selected) return;
    setSubmitting(true);
    try {
      await policiesApi.patch(selected.id, {
        summary_json: parseJsonObject(values.summary_json),
        constraints_json: parseJsonObject(values.constraints_json),
        expected_revenue_gain: values.expected_revenue_gain ? Number(values.expected_revenue_gain) : undefined,
        effective_from: values.effective_from || undefined,
        effective_to: values.effective_to || undefined,
      });
      message.success('策略已修改');
      setEditOpen(false);
      await policies.reload();
      await demandPolicyList.reload();
      if (selectedPlan) await openPlanDetail(selectedPlan, selected);

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
          <ScheduledTaskModule tasks={taskRows} onChange={setTaskRows} onSaveTask={saveScheduledTask} />

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
      <Drawer title="方案详情" open={!!selectedPlan} onClose={() => { setSelected(null); setSelectedPlan(null); setDetail(null); }} width={980}>
        {selectedPlan && <Space className="strategy-detail-actions"><Button icon={<EditOutlined />} onClick={() => editPlan(selectedPlan, selected)}>修改</Button><Button type="primary" icon={<CheckCircleOutlined />} disabled={selectedPlan.kind === 'demand' ? !['pending', 'evaluating'].includes(selectedPlan.status) : (selected?.status || selectedPlan.status) !== 'draft'} onClick={() => acceptPlan(selectedPlan, selected)}>{selectedPlan.kind === 'demand' ? '确认' : '人工确认'}</Button><Button danger icon={<StopOutlined />} disabled={selectedPlan.kind === 'demand' ? ['approved', 'rejected'].includes(selectedPlan.status) : (selected?.status || selectedPlan.status) === 'cancelled'} onClick={() => abandonPlan(selectedPlan, selected)}>{selectedPlan.kind === 'demand' ? '驳回' : '放弃'}</Button></Space>}

        {selectedPlan ? <StrategyPlanDetail plan={selectedPlan} policy={selected} detail={detail} /> : null}
      </Drawer>
      <Modal title="修改策略" open={editOpen} footer={null} onCancel={() => setEditOpen(false)}>
        <Form layout="vertical" onFinish={patch} initialValues={{ summary_json: JSON.stringify(detail?.policy.summary_json || {}, null, 2), constraints_json: JSON.stringify(detail?.policy.constraints_json || {}, null, 2), expected_revenue_gain: String(detail?.policy.expected_revenue_gain || '') }}>
          <Form.Item name="summary_json" label="策略摘要 JSON"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="constraints_json" label="约束 JSON"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="expected_revenue_gain" label="预估收益"><Input /></Form.Item>
          <Form.Item name="effective_from" label="生效时间"><Input placeholder="ISO 时间" /></Form.Item>
          <Form.Item name="effective_to" label="结束时间"><Input placeholder="ISO 时间" /></Form.Item>
          <Button loading={submitting} type="primary" htmlType="submit" block>保存</Button>
        </Form>
      </Modal>
    </>
  );
}
