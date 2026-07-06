import { Button, Form, InputNumber, Spin } from 'antd';
import { PageHeader } from '../../components/PageHeader';
import { ChartPanel } from '../../components/ChartPanel';
import { JsonBlock } from '../../components/JsonBlock';
import { ErrorState } from '../../components/ErrorState';
import { dashboardsApi } from '../../api/kongming';
import { useAsync } from '../../hooks/useAsync';
import { useState } from 'react';

export function CustomerDashboard() {
  const [customerId, setCustomerId] = useState<number | undefined>();
  const { data, error, loading, reload } = useAsync(() => dashboardsApi.customers(customerId), [customerId]);

  return (
    <>
      <PageHeader eyebrow="Customer" title="客户看板" description="按客户聚合需求、用量、收入与履约表现。" />
      <Form layout="inline" className="filter-bar" onFinish={(values) => setCustomerId(values.customer_id)}>
        <Form.Item name="customer_id" label="客户 ID"><InputNumber min={1} /></Form.Item>
        <Button htmlType="submit" type="primary">查询</Button>
        <Button onClick={() => setCustomerId(undefined)}>重置</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}>
        <ChartPanel title="客户数据快照"><JsonBlock value={data || {}} /></ChartPanel>
      </Spin>
    </>
  );
}
