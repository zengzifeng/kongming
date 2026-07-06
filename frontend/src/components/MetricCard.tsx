import type { ReactNode } from 'react';
import { ArrowRightOutlined } from '@ant-design/icons';

interface MetricCardProps {
  label: string;
  value: ReactNode;
  tone?: 'cyan' | 'amber' | 'red' | 'green' | 'purple';
  meta?: ReactNode;
  onClick?: () => void;
}

export function MetricCard({ label, value, tone = 'cyan', meta, onClick }: MetricCardProps) {
  return (
    <button className={`metric-card tone-${tone}`} onClick={onClick} type="button">
      <span className="metric-glow" />
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-meta">{meta || '实时聚合'}</div>
      {onClick && <ArrowRightOutlined className="metric-arrow" />}
    </button>
  );
}
