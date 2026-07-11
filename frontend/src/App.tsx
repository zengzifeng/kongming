import { Navigate, Route, Routes } from 'react-router-dom';
import { BrowserRouter } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { OperationsDashboard } from './pages/dashboards/OperationsDashboard';
import { RealtimeDashboard } from './pages/dashboards/RealtimeDashboard';
import { StrategyDashboard } from './pages/policies/StrategyDashboard';
import { DemandListPage } from './pages/demands/DemandListPage';
import { DemandDetailPage } from './pages/demands/DemandDetailPage';
import { NotFoundPage } from './pages/NotFoundPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<OperationsDashboard />} />
          <Route path="/demands" element={<DemandListPage />} />
          <Route path="/demands/:id" element={<DemandDetailPage />} />
          <Route path="/realtime" element={<RealtimeDashboard />} />
          <Route path="/strategies" element={<StrategyDashboard />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
