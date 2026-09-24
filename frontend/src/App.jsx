import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import ExcelImport from './pages/ExcelImport';
import CompanyList from './pages/CompanyList';
import CompanyDetail from './pages/CompanyDetail';
import Outbox from './pages/Outbox';
import Settings from './pages/Settings';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/import" element={<ExcelImport />} />
        <Route path="/companies" element={<CompanyList />} />
        <Route path="/companies/:companyId" element={<CompanyDetail />} />
        <Route path="/outbox" element={<Outbox />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
