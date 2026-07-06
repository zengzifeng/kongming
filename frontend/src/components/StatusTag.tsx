import { Tag } from 'antd';

const toneMap: Record<string, string> = {
  pending: 'processing',
  evaluating: 'cyan',
  awaiting_approval: 'gold',
  approved: 'green',
  scheduled: 'blue',
  live: 'success',
  closed: 'default',
  rejected: 'red',
  draft: 'purple',
  accepted: 'green',
  cancelled: 'red',
  recalculating: 'orange',
  expired: 'default',
  queued: 'gold',
  running: 'processing',
  success: 'green',
  failed: 'red',
  open: 'red',
  ack: 'gold',
  critical: 'red',
  warn: 'orange',
  info: 'blue',
  auto_approve: 'green',
  manual_review: 'gold',
  reject: 'red',
};

export function StatusTag({ value }: { value?: string | null }) {
  if (!value) return <Tag>未知</Tag>;
  return <Tag color={toneMap[value] || 'default'}>{value}</Tag>;
}
