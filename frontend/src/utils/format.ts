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

export function dateText(value?: string | null) {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}
