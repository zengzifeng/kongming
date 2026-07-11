import { Button, Drawer, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { CheckCircleOutlined, EditOutlined, EyeOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';

import { EmptyState } from '../../components/EmptyState';
import { ErrorState } from '../../components/ErrorState';
import { evaluationsApi, policiesApi } from '../../api/kongming';
import type { Evaluation, Policy, PolicyDetail } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText, money, numberText, percent } from '../../utils/format';
import { parseJsonObject } from '../../utils/json';

type StrategyTemplateKey = 'demand_evaluation' | 'idle' | 'busy';

const strategyTemplateOptions: Array<{ label: string; value: StrategyTemplateKey; algorithm: string }> = [
  { label: '需求评估策略', value: 'demand_evaluation', algorithm: 'demand_evaluation' },
  { label: '闲时策略', value: 'idle', algorithm: 'time_period' },
  { label: '忙时策略', value: 'busy', algorithm: 'time_period' },
];

type StrategyPlanKind = 'idle' | 'busy';

interface StrategyFlow {
  source: string;
  sourceModel: string;
  sourceRate: string;
  machines: number;
  target: string;
  targetModel: string;
  targetRate: string;
  gain: number;
}

interface StrategyAttribution {
  customer: string;
  model: string;
  density: number;
  beforeRatio: number;
  watermark: number;
  beforeVolume: number;
  afterVolume: number;
  deltaVolume: number;
  gain: number;
  fallback: string;
  series: number[];
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

const idlePlans: StrategyPlan[] = [
  {
    id: 'idle-rebalance-0712',
    kind: 'idle',
    title: '闲时算力回收与低优任务迁入',
    subtitle: '把 00:00-07:00 的空闲自建容量优先承接批处理与训练队列，释放白天三方成本压力。',
    policyNo: 'POL-OFFPEAK-0627B',
    window: '00:00-07:00',
    expectedGain: 132000,
    status: 'accepted',
    flows: [
      { source: 'GLM-5.2 空闲池', sourceModel: 'glm-5.2', sourceRate: '200w/台', machines: 8, target: '教育批处理队列', targetModel: 'glm-5.1', targetRate: '260w/台', gain: 76000 },
      { source: '低峰共享池', sourceModel: 'kimi-k2.5', sourceRate: '250w/台', machines: 6, target: '训练队列承接', targetModel: 'kimi-k2.6', targetRate: '300w/台', gain: 43000 },
      { source: 'Embedding 余量', sourceModel: 'embedding', sourceRate: '120w/台', machines: 4, target: '低优召回任务', targetModel: 'glm-5.2', targetRate: '200w/台', gain: 13000 },
    ],
    attributions: [
      { customer: '教育批处理任务', model: 'glm-5.1', density: 0.3182, beforeRatio: 0.42, watermark: 18600000, beforeVolume: 238.6, afterVolume: 477.4, deltaVolume: 238.8, gain: 76000, fallback: '百度三方', series: [820, 760, 690, 620, 570, 590, 710, 980, 1380, 1560, 1480, 1320, 1180, 1220, 1280, 1360, 1420, 1490, 1540, 1320, 1120, 960, 880, 840].map((v) => v * 10000) },
      { customer: '训练队列承接', model: 'kimi-k2.6', density: 0.2444, beforeRatio: 0.35, watermark: 13100000, beforeVolume: 176.0, afterVolume: 352.0, deltaVolume: 176.0, gain: 43000, fallback: '月暗原厂', series: [520, 540, 610, 720, 840, 920, 850, 720, 620, 580, 560, 590, 630, 680, 720, 760, 810, 890, 940, 880, 760, 650, 590, 540].map((v) => v * 10000) },
    ],
    utilRows: [
      { cluster: 'GLM-5.2', model: 'glm-5.2', capacityBefore: '8,160w', capacityAfter: '6,560w', utilizationBefore: 0.38, utilizationAfter: 0.54 },
      { cluster: 'GLM-5.1-FP8', model: 'glm-5.1', capacityBefore: '2,080w', capacityAfter: '3,640w', utilizationBefore: 0.43, utilizationAfter: 0.61 },
      { cluster: 'kimi-k2.6-mihayou', model: 'kimi-k2.6', capacityBefore: '1,200w', capacityAfter: '1,500w', utilizationBefore: 1.0, utilizationAfter: 0.87 },
    ],
    detailLead: '闲时策略以低峰窗口内的空闲自建容量为预算，优先把高毛利、低时效任务切回自建，同时保留白天峰值保护。',
  },
];

const busyPlans: StrategyPlan[] = [
  {
    id: 'busy-rebalance-0712',
    kind: 'busy',
    title: '机器腾挪流向（源模型富余 -> 目标模型紧缺）',
    subtitle: '跨模型重分配 23 台机器，把富余模型容量挪给紧缺模型，并同步调整客户切量水位线。',
    policyNo: 'POL-BUSY-0712A',
    window: '09:00-21:00',
    expectedGain: 34902,
    status: 'draft',
    flows: [
      { source: 'GLM-5.2', sourceModel: 'glm-5.2', sourceRate: '200w/台', machines: 10, target: 'kimi-k2.5-nvfp4-mihayou', targetModel: 'kimi-k2.5', targetRate: '250w/台', gain: 17576 },
      { source: 'GLM-5.2', sourceModel: 'glm-5.2', sourceRate: '200w/台', machines: 12, target: 'GLM-5.1-FP8', targetModel: 'glm-5.1', targetRate: '260w/台', gain: 16643 },
      { source: 'GLM-5.1-KSCC', sourceModel: 'glm-5.1', sourceRate: '700w/台', machines: 1, target: 'kimi-k2.6-mihayou', targetModel: 'kimi-k2.6', targetRate: '300w/台', gain: 683 },
    ],
    attributions: [
      { customer: '米哈游热点推理', model: 'kimi-k2.5', density: 0.2929, beforeRatio: 0.53, watermark: 60000000, beforeVolume: 119.9, afterVolume: 179.9, deltaVolume: 60.0, gain: 17576, fallback: '月暗原厂', series: [3200, 3500, 3800, 4200, 4600, 5100, 5600, 6100, 6500, 6800, 6630, 6400, 6200, 6500, 6700, 6900, 7100, 7350, 7600, 7200, 6800, 6100, 5200, 4300].map((v) => v * 10000) },
      { customer: 'GLM-5.1 高峰客户池', model: 'glm-5.1', density: 0.2667, beforeRatio: 0.43, watermark: 52000000, beforeVolume: 124.8, afterVolume: 187.2, deltaVolume: 62.4, gain: 16643, fallback: '百度三方', series: [2800, 3000, 3300, 3700, 4200, 4600, 5010, 5400, 5780, 6200, 5900, 5600, 5300, 5500, 5750, 5900, 6100, 6220, 6080, 5700, 5200, 4700, 3900, 3200].map((v) => v * 10000) },
      { customer: '珠海办公与 BODHIMIND', model: 'kimi-k2.6', density: 0.1582, beforeRatio: 0.91, watermark: 13100000, beforeVolume: 39.9, afterVolume: 44.2, deltaVolume: 4.3, gain: 683, fallback: '月暗原厂', series: [420, 480, 560, 680, 820, 930, 870, 760, 690, 720, 780, 840, 910, 1040, 1160, 1280, 1310, 1220, 1080, 920, 760, 620, 510, 450].map((v) => v * 10000) },
    ],
    utilRows: [
      { cluster: 'GLM-5.2', model: 'glm-5.2', capacityBefore: '8,160w', capacityAfter: '3,760w', utilizationBefore: 0.38, utilizationAfter: 0.82 },
      { cluster: 'kimi-k2.5-nvfp4-mihayou', model: 'kimi-k2.5', capacityBefore: '3,500w', capacityAfter: '6,000w', utilizationBefore: 1.0, utilizationAfter: 1.0 },
      { cluster: 'GLM-5.1-FP8', model: 'glm-5.1', capacityBefore: '2,080w', capacityAfter: '5,200w', utilizationBefore: 1.0, utilizationAfter: 1.0 },
      { cluster: 'kimi-k2.6-mihayou', model: 'kimi-k2.6', capacityBefore: '1,200w', capacityAfter: '1,500w', utilizationBefore: 1.0, utilizationAfter: 0.87 },
    ],
    detailLead: '忙时策略只在峰值可承接且整体收入净增时执行机器腾挪，收益通过抬高客户可用自建容量和切量水位线兑现。',
  },
];

function policyText(policy: Policy) {
  return `${policy.algorithm} ${policy.policy_no} ${JSON.stringify(policy.summary_json || {})}`;
}

function summaryField(policy: Policy, key: string) {
  const value = policy.summary_json?.[key];
  return typeof value === 'string' ? value : '';
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

function totalBy<T>(items: T[], selector: (item: T) => number) {
  return items.reduce((sum, item) => sum + selector(item), 0);
}

function average(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

interface EvaluationModuleProps {
  evaluations: Evaluation[];
  onCreate: () => void;
  onReload: () => void;
}

function EvaluationModule({ evaluations, onCreate, onReload }: EvaluationModuleProps) {
  const pendingCount = evaluations.filter((item) => ['draft', 'pending'].includes(item.status)).length;
  const totalMargin = totalBy(evaluations, (item) => Number(item.expected_margin || 0));
  const avgFeasibility = average(evaluations.map((item) => Number(item.feasibility_score || 0)));

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
        <div><span>待处理评估</span><strong>{numberText(pendingCount)}</strong></div>
        <div><span>平均可行性</span><strong>{percent(avgFeasibility)}</strong></div>
        <div><span>预计毛利</span><strong>{money(totalMargin)}</strong></div>
      </div>

      <Table<Evaluation>
        className="strategy-table"
        size="small"
        rowKey="id"
        dataSource={evaluations.slice(0, 6)}
        pagination={false}
        scroll={{ x: 'max-content' }}
        columns={[
          { title: '需求 ID', dataIndex: 'demand_id' },
          { title: '推荐', dataIndex: 'recommendation', render: (value) => <StatusTag value={value} /> },
          { title: '状态', dataIndex: 'status', render: (value) => <StatusTag value={value} /> },
          { title: '可行性', dataIndex: 'feasibility_score', render: percent },
          { title: '客户价值', dataIndex: 'customer_value_score', render: percent },
          { title: '预计毛利', dataIndex: 'expected_margin', render: money },
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
  const height = 140;
  const left = 38;
  const right = 10;
  const top = 12;
  const bottom = 20;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const points = item.series.map((demand, hour) => ({ hour, demand, self: Math.min(demand, item.watermark), vendor: Math.max(demand - item.watermark, 0) }));
  const maxY = Math.max(item.watermark, ...points.map((point) => point.demand)) * 1.08 || 1;
  const x = (hour: number) => left + (hour / 23) * plotWidth;
  const y = (value: number) => top + plotHeight - (value / maxY) * plotHeight;
  const selfArea = `${points.map((point) => `${x(point.hour)},${y(point.self)}`).join(' ')} ${points.slice().reverse().map((point) => `${x(point.hour)},${y(0)}`).join(' ')}`;
  const vendorArea = `${points.map((point) => `${x(point.hour)},${y(point.demand)}`).join(' ')} ${points.slice().reverse().map((point) => `${x(point.hour)},${y(point.self)}`).join(' ')}`;
  const demandLine = points.map((point, index) => `${index ? 'L' : 'M'}${x(point.hour)},${y(point.demand)}`).join('');
  const ticks = [0, Math.round(maxY / 2), Math.round(maxY)];

  return (
    <div className="strategy-wave-card">
      <div className="strategy-wave-head"><span><strong>{item.customer}</strong> <em>{item.model}</em></span><small>水位线 {formatTpm(item.watermark)} · 前自建 {percent(item.beforeRatio)}</small></div>
      <svg viewBox={`0 0 ${width} ${height}`}>
        {ticks.map((tick) => <g key={tick}><line x1={left} y1={y(tick)} x2={width - right} y2={y(tick)} /><text className="axis" x={left - 4} y={y(tick) + 3} textAnchor="end">{formatTpm(tick)}</text></g>)}
        <polygon points={selfArea} className="wave-self" />
        <polygon points={vendorArea} className="wave-vendor" />
        <path d={demandLine} className="wave-demand" />
        <polyline points={points.map((point) => `${x(point.hour)},${y(point.self)}`).join(' ')} className="wave-self-line" />
        <line x1={left} y1={y(item.watermark)} x2={width - right} y2={y(item.watermark)} className="wave-watermark" />
        {[0, 6, 12, 18, 23].map((hour) => <text className="axis" key={hour} x={x(hour)} y={height - 6} textAnchor="middle">{hour}{hour === 23 ? 'h' : ''}</text>)}
      </svg>
    </div>
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
                    <span className="strategy-flow-gain">+{money(flow.gain)}/天</span>
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
  return (
    <div className="strategy-report">
      <header className="strategy-report-head">
        <div>
          <h2>{plan.title}</h2>
          <p>{plan.detailLead}</p>
        </div>
        <StatusTag value={policy?.status || plan.status} />
      </header>
      <div className="strategy-report-kpis">
        <div><span>策略 ID</span><strong>{policy?.policy_no || plan.policyNo}</strong></div>
        <div><span>策略窗口</span><strong>{plan.window}</strong></div>
        <div><span>预计收益</span><strong className="positive">+{money(plan.expectedGain)}/天</strong></div>
        <div><span>操作项</span><strong>{numberText(detail?.actions.length || plan.flows.length)}</strong></div>
      </div>

      <section className="strategy-report-section">
        <h3><span>1</span>机器腾挪流向（源模型富余 {'->'} 目标模型紧缺）</h3>
        <div className="strategy-report-card">
          {plan.flows.map((flow) => (
            <div className="strategy-flow-row report" key={`${flow.source}-${flow.target}`}>
              <span className="strategy-flow-node"><b>{flow.source}</b><small>{flow.sourceModel} {flow.sourceRate}</small></span>
              <span className="strategy-flow-arrow">{'->'} {flow.machines}台 {'->'}</span>
              <span className="strategy-flow-node target"><b>{flow.target}</b><small>{flow.targetModel} {flow.targetRate}</small></span>
              <span className="strategy-flow-gain">+{money(flow.gain)}/天</span>
            </div>
          ))}
        </div>
      </section>

      <section className="strategy-report-section">
        <h3><span>2</span>逐调整收益核算</h3>
        <div className="strategy-formula">客户收益 = 单TPM收入 x (Σ自建_after - Σ自建_before)。自建_after(t) = min(需求(t), 切量水位线)，收益均按 24 整点波形折算为元/天。</div>
        <Table<StrategyAttribution>
          className="strategy-table strategy-report-table"
          size="small"
          rowKey={(record) => `${record.customer}-${record.model}`}
          dataSource={plan.attributions}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '客户', dataIndex: 'customer' },
            { title: '模型', dataIndex: 'model' },
            { title: '单TPM收入', dataIndex: 'density', render: (value) => Number(value).toFixed(4) },
            { title: '前自建占比', dataIndex: 'beforeRatio', render: percent },
            { title: '水位线', dataIndex: 'watermark', render: formatTpm },
            { title: 'Σ自建_before', dataIndex: 'beforeVolume', render: numberText },
            { title: 'Σ自建_after', dataIndex: 'afterVolume', render: numberText },
            { title: 'ΔΣ自建', dataIndex: 'deltaVolume', render: (value) => <span className="positive">+{numberText(value)}</span> },
            { title: '收益', dataIndex: 'gain', render: (value) => <span className="positive">+{money(value)}</span> },
          ]}
        />
      </section>

      <section className="strategy-report-section">
        <h3><span>3</span>客户实跑波形 x 切量水位线</h3>
        <div className="strategy-wave-legend"><span className="self"></span>自建承接（水位线下）<span className="vendor"></span>三方溢出（水位线上）<span className="watermark"></span>切量水位线</div>
        <div className="strategy-wave-grid">{plan.attributions.map((item) => <WaveChart item={item} key={`${item.customer}-${item.model}`} />)}</div>
      </section>

      <section className="strategy-report-section">
        <h3><span>4</span>切量前 / 后集群利用率</h3>
        <Table<StrategyUtilRow>
          className="strategy-table strategy-report-table"
          size="small"
          rowKey={(record) => record.cluster}
          dataSource={plan.utilRows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '集群', dataIndex: 'cluster' },
            { title: '模型', dataIndex: 'model' },
            { title: '容量 前', dataIndex: 'capacityBefore' },
            { title: '容量 后', dataIndex: 'capacityAfter' },
            { title: '前利用率', dataIndex: 'utilizationBefore', render: percent },
            { title: '后利用率', dataIndex: 'utilizationAfter', render: percent },
          ]}
        />
      </section>
    </div>
  );
}


export function StrategyDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const [createTemplate, setCreateTemplate] = useState<StrategyTemplateKey>('demand_evaluation');
  const [selected, setSelected] = useState<Policy | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<StrategyPlan | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const policies = useAsync(() => policiesApi.list({ page: 1, page_size: 50, exclude_status: 'cancelled' }), []);
  const evaluations = useAsync(() => evaluationsApi.list({ page: 1, page_size: 50 }), []);

  const policyItems = useMemo(() => policies.data?.items || [], [policies.data?.items]);
  const evaluationItems = useMemo(() => evaluations.data?.items || [], [evaluations.data?.items]);
  const idlePolicies = useMemo(() => policyItems.filter(isIdlePolicy), [policyItems]);
  const busyPolicies = useMemo(() => policyItems.filter(isBusyPolicy), [policyItems]);
  const idleGain = totalBy(idlePolicies, (item) => Number(item.expected_off_peak_gain || item.expected_revenue_gain || 0));
  const busyGain = totalBy(busyPolicies, (item) => Number(item.expected_revenue_gain || 0));
  const loading = policies.loading || evaluations.loading;
  const error = policies.error || evaluations.error;

  function openCreate(template: StrategyTemplateKey) {
    setCreateTemplate(template);
    setCreateOpen(true);
  }

  async function createRun(values: { template: StrategyTemplateKey }) {
    const selectedTemplate = strategyTemplateOptions.find((item) => item.value === values.template) || strategyTemplateOptions[0];
    setSubmitting(true);
    try {
      await policiesApi.createRun({ algorithm: selectedTemplate.algorithm, params: { template: selectedTemplate.label, module: selectedTemplate.value } });
      message.success(`${selectedTemplate.label}生成已提交`);
      setCreateOpen(false);
      await policies.reload();
    } finally {
      setSubmitting(false);
    }
  }

  function resolvePlanPolicy(plan: StrategyPlan, policy: Policy | null) {
    return policy || findPlanPolicy(plan, plan.kind === 'idle' ? idlePolicies : busyPolicies);
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
    await policiesApi.accept(targetPolicy.id, { operator: 'frontend' });
    message.success('策略已人工确认');
    await policies.reload();
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
    await policiesApi.cancel(targetPolicy.id, { operator: 'frontend', reason: '前端放弃策略方案' });
    message.success('策略方案已放弃');
    setSelected(null);
    setSelectedPlan(null);
    setDetail(null);
    await policies.reload();
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
      {error ? <ErrorState error={error} onRetry={() => { void policies.reload(); void evaluations.reload(); }} /> : null}
      <Spin spinning={loading}>
        <div className="strategy-dashboard-grid page-section">
          <EvaluationModule evaluations={evaluationItems} onCreate={() => openCreate('demand_evaluation')} onReload={() => { void evaluations.reload(); }} />
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
        {selectedPlan && <Space className="strategy-detail-actions"><Button icon={<EditOutlined />} onClick={() => editPlan(selectedPlan, selected)}>修改</Button><Button type="primary" icon={<CheckCircleOutlined />} disabled={(selected?.status || selectedPlan.status) !== 'draft'} onClick={() => acceptPlan(selectedPlan, selected)}>人工确认</Button><Button danger icon={<StopOutlined />} disabled={(selected?.status || selectedPlan.status) === 'cancelled'} onClick={() => abandonPlan(selectedPlan, selected)}>放弃</Button></Space>}
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
