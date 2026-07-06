import { Alert, Button } from 'antd';

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
}

function getMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return '请求失败，请稍后重试';
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  return (
    <Alert
      type="error"
      showIcon
      message="数据加载失败"
      description={getMessage(error)}
      action={onRetry ? <Button onClick={onRetry}>重试</Button> : undefined}
    />
  );
}
