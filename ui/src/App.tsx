import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import Landing from './pages/Landing'
import Settings from './pages/Settings'
import LegalDoc from './pages/LegalDoc'
import { AuthProvider, useAuth } from './state/AuthContext'

// The admin area is the only consumer of Monaco (via the template tabs) and is
// visited rarely, so the whole admin surface is code-split out of the initial
// bundle. Panels use named exports, hence the `default` adapter React.lazy
// requires.
const Admin = lazy(() => import('./pages/Admin'))
const ProductsPanel = lazy(() =>
  import('./components/ProductsPanel').then((m) => ({ default: m.ProductsPanel })),
)
const DeploymentsPanel = lazy(() =>
  import('./components/DeploymentsPanel').then((m) => ({ default: m.DeploymentsPanel })),
)
const UsersPanel = lazy(() =>
  import('./components/UsersPanel').then((m) => ({ default: m.UsersPanel })),
)
const PlansPanel = lazy(() =>
  import('./components/PlansPanel').then((m) => ({ default: m.PlansPanel })),
)
const SubdomainPanel = lazy(() =>
  import('./components/subdomain/SubdomainPanel').then((m) => ({ default: m.SubdomainPanel })),
)
const SshKeysPanel = lazy(() =>
  import('./components/SshKeysPanel').then((m) => ({ default: m.SshKeysPanel })),
)

/**
 * Layout route that wraps the signed-in app pages in the AppShell chrome. The
 * Suspense boundary here covers the lazily-loaded admin routes (Admin and its
 * panels) that render into this Outlet.
 */
function AppShellLayout() {
  return (
    <AppShell>
      <Suspense fallback={null}>
        <Outlet />
      </Suspense>
    </AppShell>
  )
}

/**
 * Auth-aware root: the same '/' URL serves the anonymous landing page to
 * visitors and the provisioning dashboard to signed-in users. Legal documents
 * live at /legal/:slug and render bare (outside the AppShell/landing chrome) so
 * they print cleanly and stay reachable whether or not the visitor is signed in.
 */
function AuthedApp() {
  const { user, loading } = useAuth()

  // Avoid flashing the landing page while the initial /api/me check runs.
  if (loading) return null

  return (
    <Routes>
      <Route path="/legal/:slug" element={<LegalDoc />} />
      {user ? (
        <Route element={<AppShellLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/settings" element={<Settings />}>
            <Route index element={<Navigate to="domain" replace />} />
            <Route path="domain" element={<SubdomainPanel />} />
            <Route path="ssh-keys" element={<SshKeysPanel />} />
          </Route>
          <Route path="/admin" element={<Admin />}>
            <Route index element={<Navigate to="products" replace />} />
            <Route path="products" element={<ProductsPanel />} />
            <Route path="deployments" element={<DeploymentsPanel />} />
            <Route path="users" element={<UsersPanel />} />
            <Route path="plans" element={<PlansPanel />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      ) : (
        <Route path="*" element={<Landing />} />
      )}
    </Routes>
  )
}

function App() {
  return (
    <AuthProvider>
      <AuthedApp />
    </AuthProvider>
  )
}

export default App
