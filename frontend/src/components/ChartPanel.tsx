import type { ReactNode } from 'react';

interface ChartPanelProps {
  title: string;
  extra?: ReactNode;
  children: ReactNode;
}

export function ChartPanel({ title, extra, children }: ChartPanelProps) {
  return (
    <section className="chart-panel">
      <div className="chart-panel-head">
        <h3>{title}</h3>
        {extra}
      </div>
      <div className="chart-panel-body">{children}</div>
    </section>
  );
}
