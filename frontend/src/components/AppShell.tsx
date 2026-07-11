import { Layout, Menu } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  DashboardOutlined,
  DatabaseOutlined,
  FundProjectionScreenOutlined,
  NodeIndexOutlined,
} from '@ant-design/icons';

const { Sider, Content } = Layout;

const items = [
  { key: '/overview', icon: <DashboardOutlined />, label: '运营总览' },
  { key: '/demands', icon: <DatabaseOutlined />, label: '需求看板' },
  { key: '/realtime', icon: <NodeIndexOutlined />, label: '资源看板' },
  { key: '/strategies', icon: <FundProjectionScreenOutlined />, label: '策略看板' },
];

function selectedKey(pathname: string) {
  if (pathname.startsWith('/demands')) return '/demands';
  return items.find((item) => pathname.startsWith(item.key))?.key || '/overview';
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Layout className="app-shell">
      <Sider width={248} className="app-sider" breakpoint="lg" collapsedWidth="0">
        <div className="brand-block">
          <div className="brand-mark">KM</div>
          <div>
            <div className="brand-title">孔明</div>
            <div className="brand-subtitle">AI Gateway Ops</div>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey(location.pathname)]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout className="app-main">
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
