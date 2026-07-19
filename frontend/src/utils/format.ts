export function money(value?: number | null) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
}

export function numberText(value?: number | null) {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

export function percent(value?: number | null) {
  const n = Number(value || 0);
  return `${(n <= 1 ? n * 100 : n).toFixed(1)}%`;
}

// 利用率专用：入参恒为「占比小数」(如 1.101=110.1%)，一律 ×100；可超过 100%。
// 不用 percent()，因其对 >1 的值会当成「已是百分数」而漏乘 100，导致 110.1% 被显示成 1.1%。
export function ratioPercent(value?: number | null) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

export function dateText(value?: string | null) {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}
