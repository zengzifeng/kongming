import { Spin, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ErrorState } from '../../components/ErrorState';
import { PageHeader } from '../../components/PageHeader';
import { revenueApi } from '../../api/kongming';
import type { RevenuePeakShavingItem, RevenueTimePeriodItem } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { money, numberText, percent } from '../../utils/format';

function totalBy<T>(items: T[], selector: (item: T) => number) {
  return items.reduce((sum, item) => sum + selector(item), 0);
}

function peakNetRevenue(item: RevenuePeakShavingItem) {
  return item.self_cost_reduction - item.vendor_cost_increase + item.directed_shift_revenue;
}

function RevenueStat({ label, value, tone = 'cyan' }: { label: string; value: string; tone?: 'cyan' | 'green' | 'amber' | 'red' }) {
  return (
    <div className={`revenue-stat revenue-stat-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TimePeriodRevenueModule({ title, rows, tone }: { title: string; rows: RevenueTimePeriodItem[]; tone: 'green' | 'amber' }) {
  const columns: ColumnsType<RevenueTimePeriodItem> = [
    { title: '日期', dataIndex: 'date', fixed: 'left', width: 118 },
    { title: '客户名称', dataIndex: 'customer_name', fixed: 'left', width: 150 },
    { title: '模型名称', dataIndex: 'model_name', width: 210 },
    { title: '售卖折扣', dataIndex: 'sale_discount', width: 110, align: 'right', render: percent },
    { title: '采购折扣', dataIndex: 'purchase_discount', width: 110, align: 'right', render: percent },
    { title: '自建净增收入', dataIndex: 'self_incremental_revenue', width: 140, align: 'right', render: money },
    { title: '三方减少成本', dataIndex: 'vendor_cost_reduction', width: 140, align: 'right', render: money },
    { title: '总收益', dataIndex: 'total_revenue', width: 130, align: 'right', render: money },
    { title: '百万token单价', dataIndex: 'price_per_million_tokens', width: 140, align: 'right', render: (value: number) => money(value) },
  ];

  return (
    <section className={`wire-card revenue-module revenue-module-${tone}`}>
      <div className="revenue-module-head">
        <div>
          <div className="revenue-module-eyebrow">Revenue</div>
          <div className="wire-card-title">{title}</div>
        </div>
        <RevenueStat label="总收益" value={money(totalBy(rows, (item) => item.total_revenue))} tone={tone} />
      </div>
      <div className="revenue-stat-grid">
        <RevenueStat label="自建净增收入" value={money(totalBy(rows, (item) => item.self_incremental_revenue))} tone="cyan" />
        <RevenueStat label="三方减少成本" value={money(totalBy(rows, (item) => item.vendor_cost_reduction))} tone="green" />
        <RevenueStat label="平均售卖折扣" value={percent(totalBy(rows, (item) => item.sale_discount) / Math.max(rows.length, 1))} tone="amber" />
      </div>
      <Table<RevenueTimePeriodItem>
        className="revenue-table"
        rowKey="id"
        size="small"
        dataSource={rows}
        columns={columns}
        pagination={false}
        scroll={{ x: 1248 }}
      />
    </section>
  );
}

function PeakShavingRevenueModule({ rows }: { rows: RevenuePeakShavingItem[] }) {
  const columns: ColumnsType<RevenuePeakShavingItem> = [
    { title: '日期', dataIndex: 'date', fixed: 'left', width: 118 },
    { title: '客户名称', dataIndex: 'customer_name', fixed: 'left', width: 150 },
    { title: '模型名称', dataIndex: 'model_name', width: 210 },
    { title: '削峰前峰值TPM', dataIndex: 'peak_tpm_before', width: 150, align: 'right', render: numberText },
    { title: '削峰水位', dataIndex: 'peak_watermark', width: 110, align: 'right', render: percent },
    { title: '节省TPM', dataIndex: 'saved_tpm', width: 130, align: 'right', render: numberText },
    { title: '削峰前机器台数', dataIndex: 'machines_before', width: 140, align: 'right' },
    { title: '削峰后机器台数', dataIndex: 'machines_after', width: 140, align: 'right' },
    { title: '自建减少成本', dataIndex: 'self_cost_reduction', width: 140, align: 'right', render: money },
    { title: '三方增加成本', dataIndex: 'vendor_cost_increase', width: 140, align: 'right', render: money },
    { title: '定向腾挪增加收入', dataIndex: 'directed_shift_revenue', width: 160, align: 'right', render: money },
  ];

  return (
    <section className="wire-card revenue-module revenue-module-cyan revenue-module-wide">
      <div className="revenue-module-head">
        <div>
          <div className="revenue-module-eyebrow">Peak Shaving</div>
          <div className="wire-card-title">削峰收益</div>
        </div>
        <RevenueStat label="净收益" value={money(totalBy(rows, peakNetRevenue))} tone="cyan" />
      </div>
      <div className="revenue-stat-grid revenue-stat-grid-peak">
        <RevenueStat label="节省TPM" value={numberText(totalBy(rows, (item) => item.saved_tpm))} tone="cyan" />
        <RevenueStat label="自建减少成本" value={money(totalBy(rows, (item) => item.self_cost_reduction))} tone="green" />
        <RevenueStat label="三方增加成本" value={money(totalBy(rows, (item) => item.vendor_cost_increase))} tone="red" />
        <RevenueStat label="定向腾挪增加收入" value={money(totalBy(rows, (item) => item.directed_shift_revenue))} tone="amber" />
      </div>
      <Table<RevenuePeakShavingItem>
        className="revenue-table"
        rowKey="id"
        size="small"
        dataSource={rows}
        columns={columns}
        pagination={false}
        scroll={{ x: 1588 }}
      />
    </section>
  );
}

export function RevenueDashboardPage() {
  const { data, error, loading, reload } = useAsync(() => revenueApi.dashboard(), []);
  const idleRows = data?.idle || [];
  const busyRows = data?.busy || [];
  const peakRows = data?.peak_shaving || [];
  const totalRevenue = totalBy(idleRows, (item) => item.total_revenue)
    + totalBy(busyRows, (item) => item.total_revenue)
    + totalBy(peakRows, peakNetRevenue);

  return (
    <>
      <PageHeader eyebrow="Revenue" title="收益看板" description="按闲时、忙时和削峰三类收益口径查看客户模型明细与收益拆分。" />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <div className="revenue-summary-grid page-section">
          <RevenueStat label="总收益" value={money(totalRevenue)} tone="green" />
          <RevenueStat label="闲时收益" value={money(totalBy(idleRows, (item) => item.total_revenue))} tone="green" />
          <RevenueStat label="忙时收益" value={money(totalBy(busyRows, (item) => item.total_revenue))} tone="amber" />
          <RevenueStat label="削峰收益" value={money(totalBy(peakRows, peakNetRevenue))} tone="cyan" />
        </div>
        <div className="revenue-board page-section">
          <TimePeriodRevenueModule title="闲时收益" rows={idleRows} tone="green" />
          <TimePeriodRevenueModule title="忙时收益" rows={busyRows} tone="amber" />
          <PeakShavingRevenueModule rows={peakRows} />
        </div>
      </Spin>
    </>
  );
}
