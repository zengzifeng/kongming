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

interface StatusTagProps {
  value?: string | null;
  label?: string | null;
}

export function StatusTag({ value, label }: StatusTagProps) {
  if (!value) return <Tag>{label || '未知'}</Tag>;
  return <Tag color={toneMap[value] || 'default'}>{label || value}</Tag>;
}

