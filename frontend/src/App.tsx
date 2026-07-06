import { Navigate, Route, Routes } from 'react-router-dom';
import { BrowserRouter } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { OperationsDashboard } from './pages/dashboards/OperationsDashboard';
import { RealtimeDashboard } from './pages/dashboards/RealtimeDashboard';
import { IdleDashboard } from './pages/dashboards/IdleDashboard';
import { BusyDashboard } from './pages/dashboards/BusyDashboard';
import { PeakShavingDashboard } from './pages/dashboards/PeakShavingDashboard';
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
          <Route path="/idle" element={<IdleDashboard />} />
          <Route path="/busy" element={<BusyDashboard />} />
          <Route path="/peak-shaving" element={<PeakShavingDashboard />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
