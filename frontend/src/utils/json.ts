export function parseJsonObject(input?: string): Record<string, unknown> | null {
  if (!input?.trim()) return null;
  const parsed = JSON.parse(input);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('请输入 JSON 对象');
  return parsed as Record<string, unknown>;
}

export function parseNumberList(input?: string): number[] | undefined {
  if (!input?.trim()) return undefined;
  return input.split(',').map((item) => Number(item.trim())).filter((item) => Number.isFinite(item));
}
