import { Button, message, Spin, Table } from 'antd';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ChartPanel } from '../../components/ChartPanel';
import { ErrorState } from '../../components/ErrorState';
import { syncApi } from '../../api/kongming';
import type { RawFiling, SyncBatch } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText } from '../../utils/format';

export function SyncCenterPage() {
  const [batchId, setBatchId] = useState<number | undefined>();
  const batches = useAsync(() => syncApi.batches({ page: 1, page_size: 10 }), []);
  const filings = useAsync(() => syncApi.rawFilings({ page: 1, page_size: 10, batch_id: batchId }), [batchId]);

  async function run() {
    await syncApi.run();
    message.success('同步已提交');
    await batches.reload();
  }

  return (
    <>
      <PageHeader eyebrow="Sync" title="同步中心" description="触发报备同步，查看同步批次与原始报备 payload。" actions={<Button type="primary" onClick={run}>手动同步</Button>} />
      {batches.error && <ErrorState error={batches.error} onRetry={batches.reload} />}
      <Spin spinning={batches.loading}><Table<SyncBatch> rowKey="id" dataSource={batches.data?.items || []} onRow={(record) => ({ onClick: () => setBatchId(record.id) })} pagination={false} columns={[{ title: '批次号', dataIndex: 'batch_no' }, { title: '来源', dataIndex: 'source' }, { title: '触发', dataIndex: 'triggered_by' }, { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> }, { title: '拉取', dataIndex: 'total_pulled' }, { title: '新增', dataIndex: 'total_inserted' }, { title: '更新', dataIndex: 'total_updated' }, { title: '跳过', dataIndex: 'total_skipped' }, { title: '开始', dataIndex: 'started_at', render: dateText }]} /></Spin>
      <ChartPanel title={batchId ? `原始报备 · 批次 ${batchId}` : '原始报备'}>
        {filings.error ? <ErrorState error={filings.error} onRetry={filings.reload} /> : null}
        <Table<RawFiling> rowKey="id" loading={filings.loading} dataSource={filings.data?.items || []} pagination={false} columns={[{ title: '报备 ID', dataIndex: 'report_id' }, { title: '拉取时间', dataIndex: 'pulled_at', render: dateText }, { title: 'Hash', dataIndex: 'hash' }, { title: 'Payload', dataIndex: 'payload_json', render: (v) => <JsonBlock value={v} /> }]} />
      </ChartPanel>
    </>
  );
}
