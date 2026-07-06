import { Button, Form, Input, message, Modal, Select, Space, Spin, Table } from 'antd';
import { useState } from 'react';
import { PageHeader } from '../../components/PageHeader';
import { StatusTag } from '../../components/StatusTag';
import { JsonBlock } from '../../components/JsonBlock';
import { ErrorState } from '../../components/ErrorState';
import { alertsApi } from '../../api/kongming';
import type { AlertItem } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { dateText } from '../../utils/format';

export function AlertCenterPage() {
  const [query, setQuery] = useState({ page: 1, page_size: 10 });
  const { data, error, loading, reload } = useAsync(() => alertsApi.list(query), [JSON.stringify(query)]);

  function operate(item: AlertItem, action: 'ack' | 'close') {
    Modal.confirm({ title: action === 'ack' ? '确认告警' : '关闭告警', content: item.message, onOk: async () => { await alertsApi.patch(item.id, { action, operator: 'frontend' }); message.success('告警已更新'); await reload(); } });
  }

  return (
    <>
      <PageHeader eyebrow="Alerts" title="告警中心" description="处理开放、已确认和已关闭的系统告警。" />
      <Form layout="inline" className="filter-bar" onFinish={(values) => setQuery({ ...query, ...values, page: 1 })}>
        <Form.Item name="status" label="状态"><Select allowClear style={{ width: 150 }} options={['open','ack','closed'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="severity" label="等级"><Select allowClear style={{ width: 150 }} options={['info','warn','critical'].map((v) => ({ label: v, value: v }))} /></Form.Item>
        <Form.Item name="type" label="类型"><Input allowClear /></Form.Item>
        <Button type="primary" htmlType="submit">筛选</Button>
      </Form>
      {error && <ErrorState error={error} onRetry={reload} />}
      <Spin spinning={loading}><Table<AlertItem> rowKey="id" dataSource={data?.items || []} pagination={{ current: data?.page || 1, pageSize: data?.page_size || 10, total: data?.total || 0, onChange: (page, pageSize) => setQuery({ ...query, page, page_size: pageSize }) }} columns={[{ title: '类型', dataIndex: 'alert_type' }, { title: '等级', dataIndex: 'severity', render: (v) => <StatusTag value={v} /> }, { title: '状态', dataIndex: 'status', render: (v) => <StatusTag value={v} /> }, { title: '消息', dataIndex: 'message' }, { title: '主体', render: (_, r) => `${r.subject_type || '-'}:${r.subject_id || '-'}` }, { title: '创建', dataIndex: 'created_at', render: dateText }, { title: '载荷', dataIndex: 'payload_json', render: (v) => <JsonBlock value={v} /> }, { title: '操作', render: (_, r) => <Space>{r.status === 'open' && <Button onClick={() => operate(r, 'ack')}>ack</Button>}{r.status !== 'closed' && <Button danger onClick={() => operate(r, 'close')}>close</Button>}</Space> }]} /></Spin>
    </>
  );
}
