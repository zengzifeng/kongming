import { Radio, Spin } from 'antd';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { ChartPanel } from '../../components/ChartPanel';
import { JsonBlock } from '../../components/JsonBlock';
import { ErrorState } from '../../components/ErrorState';
import { dashboardsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';

export function ManagementDashboard() {
  const [range, setRange] = useState('7d');
  const { data, error, loading, reload } = useAsync(() => dashboardsApi.management(range), [range]);
  return (
    <>
      <PageHeader eyebrow="Management" title="管理看板" description="面向管理视角查看收入、成本、毛利与策略贡献。" actions={<Radio.Group value={range} onChange={(e) => setRange(e.target.value)} optionType="button" buttonStyle="solid" options={[{label:'7d', value:'7d'}, {label:'30d', value:'30d'}, {label:'90d', value:'90d'}]} />} />
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}><ChartPanel title="管理指标"><JsonBlock value={data || {}} /></ChartPanel></Spin>
    </>
  );
}
