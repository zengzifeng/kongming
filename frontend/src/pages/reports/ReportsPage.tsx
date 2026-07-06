import { Button, Form, Input, Spin, Tabs } from 'antd';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { ChartPanel } from '../../components/ChartPanel';
import { JsonBlock } from '../../components/JsonBlock';
import { ErrorState } from '../../components/ErrorState';
import { reportsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';

export function ReportsPage() {
  const [tab, setTab] = useState('weekly');
  const [week, setWeek] = useState<string | undefined>();
  const [month, setMonth] = useState<string | undefined>();
  const weekly = useAsync(() => reportsApi.weekly(week), [week]);
  const monthly = useAsync(() => reportsApi.monthly(month), [month]);

  return (
    <>
      <PageHeader eyebrow="Reports" title="运营报表" description="查看周报和月报摘要，后端返回结构变化时以 JSON 方式兜底展示。" />
      <Tabs activeKey={tab} onChange={setTab} items={[{ key: 'weekly', label: '周报' }, { key: 'monthly', label: '月报' }]} />
      {tab === 'weekly' && <>
        <Form layout="inline" className="filter-bar" onFinish={(v) => setWeek(v.week)}><Form.Item name="week" label="周"><Input placeholder="如 2026-W26" /></Form.Item><Button type="primary" htmlType="submit">查询</Button></Form>
        {weekly.error && <ErrorState error={weekly.error} onRetry={weekly.reload} />}
        <Spin spinning={weekly.loading}><ChartPanel title="周报摘要"><JsonBlock value={weekly.data || {}} /></ChartPanel></Spin>
      </>}
      {tab === 'monthly' && <>
        <Form layout="inline" className="filter-bar" onFinish={(v) => setMonth(v.month)}><Form.Item name="month" label="月"><Input placeholder="如 2026-06" /></Form.Item><Button type="primary" htmlType="submit">查询</Button></Form>
        {monthly.error && <ErrorState error={monthly.error} onRetry={monthly.reload} />}
        <Spin spinning={monthly.loading}><ChartPanel title="月报摘要"><JsonBlock value={monthly.data || {}} /></ChartPanel></Spin>
      </>}
    </>
  );
}
