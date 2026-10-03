import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { IdleGuard } from './IdleGuard'

export function ProtectedRoute() {
  const { token, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center bg-surface">
        <div className="h-10 w-10 rounded-full border-4 border-cyan border-t-transparent animate-spin" />
      </div>
    )
  }

  if (!token) return <Navigate to="/login" replace />
  return (
    <>
      <Outlet />
      <IdleGuard />
    </>
  )
}
