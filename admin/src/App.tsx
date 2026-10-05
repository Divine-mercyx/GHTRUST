import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { SupportPage } from './pages/SupportPage'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AuthProvider, useAuth } from './lib/auth'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { ApplicationDetailPage } from './pages/ApplicationDetailPage'
import { LoanProductsPage } from './pages/LoanProductsPage'
import { InvestmentsPage } from './pages/InvestmentsPage'
import { TeamPage } from './pages/TeamPage'
import { CustomersPage } from './pages/CustomersPage'
import { CustomerDetailPage } from './pages/CustomerDetailPage'
import { SettingsPage } from './pages/SettingsPage'
import { ProfilePage } from './pages/ProfilePage'
import { DeleteAccountPage } from './pages/DeleteAccountPage'

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth()
  if (loading) return null
  if (token) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicOnly>
                <LoginPage />
              </PublicOnly>
            }
          />
          {/* Public: customers delete their account without the app (Google Play requirement). */}
          <Route path="/delete-account" element={<DeleteAccountPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/applications" element={<ApplicationsPage />} />
            <Route path="/applications/:id" element={<ApplicationDetailPage />} />
            <Route path="/loan-products" element={<LoanProductsPage />} />
            <Route path="/investments" element={<InvestmentsPage />} />
            <Route path="/team" element={<TeamPage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/support" element={<SupportPage />} />
            <Route path="/customers/:id" element={<CustomerDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
