import { Button } from 'antd';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="not-found surface-card">
      <PageHeader eyebrow="404" title="页面不存在" description="当前路径没有对应的运营模块，请返回运营总览继续操作。" actions={<Button type="primary" onClick={() => navigate('/dashboard/operations')}>返回运营总览</Button>} />
      <div className="not-found-code">NO SIGNAL</div>
    </div>
  );
}
