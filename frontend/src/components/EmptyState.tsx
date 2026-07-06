import { Empty } from 'antd';

export function EmptyState({ description = '暂无数据' }: { description?: string }) {
  return <Empty className="km-empty" description={description} />;
}
