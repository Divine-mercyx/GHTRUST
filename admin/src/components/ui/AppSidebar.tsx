import clsx from 'clsx'
import {
  ChevronLeft,
  FileText,
  HandCoins,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Pin,
  Search,
  Settings,
  TrendingUp,
  UserCog,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../../lib/auth'
import { StaffAvatar } from '../StaffAvatar'
import { hasAnyPermission, hasPermission } from '../../lib/permissions'
import { SIDEBAR_EASE, SIDEBAR_MS } from '../../lib/sidebarPin'

type NavItem = {
  to: string
  label: string
  icon: React.ReactNode
  end?: boolean
  disabled?: boolean
}

function buildSections(
  canManageTeam: boolean,
  canViewCustomers: boolean,
  canViewSettings: boolean,
  canViewSupport: boolean,
  canViewInvestments: boolean,
): { title: string; items: NavItem[] }[] {
  const systemItems: NavItem[] = []
  if (canManageTeam) {
    systemItems.push({ to: '/team', label: 'Team', icon: <UserCog size={16} /> })
  }
  if (canViewCustomers) {
    systemItems.push({ to: '/customers', label: 'Customers', icon: <Users size={16} /> })
  } else {
    systemItems.push({ to: '/dashboard', label: 'Customers', icon: <Users size={16} />, disabled: true })
  }
  if (canViewSupport) {
    systemItems.push({ to: '/support', label: 'Support', icon: <LifeBuoy size={16} /> })
  }
  if (canViewSettings) {
    systemItems.push({ to: '/settings', label: 'Settings', icon: <Settings size={16} /> })
  } else {
    systemItems.push({ to: '/dashboard', label: 'Settings', icon: <Settings size={16} />, disabled: true })
  }
  return [
    {
      title: 'Overview',
      items: [{ to: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, end: true }],
    },
    {
      title: 'Lending',
      items: [
        { to: '/applications', label: 'Loan queue', icon: <FileText size={16} /> },
        { to: '/loan-products', label: 'Loan products', icon: <HandCoins size={16} /> },
      ],
    },
    ...(canViewInvestments
      ? [{ title: 'Investing', items: [{ to: '/investments', label: 'Investments', icon: <TrendingUp size={16} /> }] }]
      : []),
    { title: 'System', items: systemItems },
  ]
}

interface AppSidebarProps {
  /** Showing only the icon rail. */
  collapsed: boolean
  /** Kept open by the user (otherwise it only opens while hovered). */
  pinned: boolean
  /** Open as a peek, overlaying the page. */
  floating?: boolean
  onTogglePin: () => void
  onNavigate?: () => void
}

const motion = { transitionTimingFunction: SIDEBAR_EASE, transitionDuration: `${SIDEBAR_MS}ms` }

/**
 * Text that fades and folds away when the rail collapses. It stays mounted and never wraps,
 * so nothing reflows mid-animation; icons keep fixed positions and only the width changes.
 */
function Fade({ hidden, className, children }: { hidden: boolean; className?: string; children: React.ReactNode }) {
  return (
    <span
      aria-hidden={hidden || undefined}
      className={clsx('whitespace-nowrap transition-opacity', hidden ? 'opacity-0' : 'opacity-100', className)}
      style={motion}
    >
      {children}
    </span>
  )
}

export function AppSidebar({ collapsed, pinned, floating, onTogglePin, onNavigate }: AppSidebarProps) {
  const { staff, logout } = useAuth()
  const [search, setSearch] = useState('')
  const sections = buildSections(
    hasAnyPermission(staff, ['staff:read', 'role:read']),
    hasPermission(staff, 'loan:read'),
    hasPermission(staff, 'loan:read'),
    hasPermission(staff, 'support:read'),
    hasPermission(staff, 'investment:read'),
  )

  // Geometry: 72px rail. Nav rows start 12px in with 16px left padding, so every icon is
  // centred on x=36 whether the sidebar is collapsed or open.
  return (
    <aside
      className={clsx(
        'flex flex-col h-screen bg-navy border-r border-white/10 transition-[width,box-shadow] overflow-hidden',
        collapsed ? 'w-[72px]' : 'w-[272px]',
        floating && 'shadow-2xl shadow-black/30',
      )}
      style={motion}
    >
      <div className="pt-5 pb-3 px-3">
        <div className="flex items-center h-9">
          <div
            className={clsx(
              'rounded-lg bg-cyan flex items-center justify-center shrink-0 transition-[width,height,margin]',
              collapsed ? 'h-7 w-7 ml-0' : 'h-9 w-9 ml-1',
            )}
            style={motion}
          >
            <span className={clsx('font-bold text-white tracking-tight', collapsed ? 'text-[10px]' : 'text-[11px]')}>GH</span>
          </div>
          <div
            className={clsx('leading-tight min-w-0 overflow-hidden transition-[max-width,margin,opacity]', collapsed ? 'max-w-0 ml-0 opacity-0' : 'max-w-[160px] ml-3 opacity-100')}
            style={motion}
            aria-hidden={collapsed || undefined}
          >
            <p className="text-[15px] font-semibold text-white tracking-tight whitespace-nowrap">GH Trust</p>
            <p className="text-[11px] text-white/55 font-medium whitespace-nowrap">Staff operations</p>
          </div>
          {/* Collapsed, the toggle sits beside the smaller logo (12 + 28 + 4 + 24 = 68 of 72px). */}
          <button
            type="button"
            onClick={onTogglePin}
            className={clsx(
              'rounded-lg flex items-center justify-center shrink-0 text-white/55 hover:text-white hover:bg-white/10 transition-colors',
              collapsed ? 'h-7 w-6 ml-1' : 'h-8 w-8 ml-auto',
            )}
            aria-label={pinned ? 'Collapse sidebar' : 'Keep sidebar open'}
            aria-pressed={pinned}
            title={pinned ? 'Collapse sidebar' : 'Keep sidebar open'}
          >
            {collapsed ? (
              <ChevronLeft size={14} className="rotate-180" />
            ) : pinned ? (
              <ChevronLeft size={16} />
            ) : (
              <Pin size={15} />
            )}
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="pb-4 px-3">
        <label className="relative flex items-center h-10 rounded-lg bg-white/10 ring-1 ring-white/10 cursor-text">
          <span className="flex items-center justify-center shrink-0 w-12">
            <Search size={15} className="text-white/65" />
          </span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            tabIndex={collapsed ? -1 : undefined}
            aria-label="Search"
            className={clsx(
              'flex-1 min-w-0 bg-transparent border-none outline-none text-[13px] text-white placeholder:text-white/45 pr-3 transition-opacity',
              collapsed ? 'opacity-0' : 'opacity-100',
            )}
            style={motion}
          />
        </label>
      </div>

      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-3">
        {sections.map((section, i) => (
          <div key={section.title} className={clsx(i > 0 && 'mt-3')}>
            {/* Section titles fold away when collapsing, so the icons glide up; they unfold
                on opening, so the icons glide back down. */}
            <div
              className={clsx('grid transition-[grid-template-rows,opacity]', collapsed ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100')}
              style={motion}
              aria-hidden={collapsed || undefined}
            >
              <p className="overflow-hidden px-4 text-[10px] font-semibold uppercase tracking-widest text-white/50">
                <span className="block pt-2 pb-2">{section.title}</span>
              </p>
            </div>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const row = 'flex items-center gap-3 h-10 pl-4 pr-3 rounded-lg text-[13px] font-medium'
                if (item.disabled) {
                  return (
                    <li key={item.label}>
                      <span className={clsx(row, 'text-white/30 cursor-not-allowed')} title={collapsed ? item.label : undefined}>
                        <span className="shrink-0">{item.icon}</span>
                        <Fade hidden={collapsed} className="flex-1">{item.label}</Fade>
                        <Fade hidden={collapsed} className="text-[9px] uppercase tracking-wide font-semibold">
                          Soon
                        </Fade>
                      </span>
                    </li>
                  )
                }
                return (
                  <li key={item.label}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      onClick={onNavigate}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) =>
                        clsx(
                          row,
                          'transition-colors duration-200',
                          isActive
                            ? 'bg-white/15 text-white ring-1 ring-white/15'
                            : 'text-white/65 hover:text-white hover:bg-white/10',
                        )
                      }
                    >
                      <span className="shrink-0">{item.icon}</span>
                      <Fade hidden={collapsed}>{item.label}</Fade>
                    </NavLink>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="mt-auto border-t border-white/10 p-3">
        {/* Collapsed, the rail only has room for the avatar: sign-out folds to zero width
            (it's back as soon as the sidebar opens, e.g. on hover). */}
        <div className={clsx('flex items-center rounded-lg transition-[gap]', collapsed ? 'gap-0' : 'gap-1')} style={motion}>
          <NavLink
            to="/profile"
            onClick={onNavigate}
            title={collapsed ? 'My profile' : undefined}
            aria-label="My profile"
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 p-1.5 rounded-lg min-w-0 flex-1 transition-colors',
                isActive ? 'bg-white/15' : 'hover:bg-white/10',
              )
            }
          >
            <StaffAvatar staff={staff} size="sm" className="ring-1 ring-white/25" />
            <div
              className={clsx('min-w-0 flex-1 transition-opacity', collapsed ? 'opacity-0' : 'opacity-100')}
              style={motion}
              aria-hidden={collapsed || undefined}
            >
              <p className="text-[13px] font-semibold text-white truncate">{staff?.full_name}</p>
              <p className="text-[11px] text-white/50 truncate">{staff?.job_title || staff?.role?.name || staff?.email || 'Staff'}</p>
            </div>
          </NavLink>
          <button
            type="button"
            onClick={logout}
            tabIndex={collapsed ? -1 : undefined}
            aria-hidden={collapsed || undefined}
            className={clsx(
              'h-8 flex items-center justify-center rounded-lg overflow-hidden shrink-0 text-white/50 hover:text-rose-300 hover:bg-white/10 transition-[width,opacity,color,background-color]',
              collapsed ? 'w-0 opacity-0 pointer-events-none' : 'w-8 opacity-100',
            )}
            style={motion}
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut size={15} className="shrink-0" />
          </button>
        </div>
      </div>
    </aside>
  )
}
