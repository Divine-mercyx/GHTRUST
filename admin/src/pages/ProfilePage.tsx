import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { Check, KeyRound, LogOut, PanelLeft, ShieldCheck, UserRound } from 'lucide-react'
import { AdminLayout } from '../components/AdminLayout'
import { SessionTimeoutCard } from '../components/SessionTimeoutCard'
import { StaffAvatar } from '../components/StaffAvatar'
import { DashCard } from '../components/ui'
import { adminAuthApi, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AVATAR_COLORS } from '../lib/avatar'
import { useSidebarPin } from '../lib/sidebarPin'

/** "loan:configure_workflow" → ["Loans", "Configure workflow"] */
function describePermission(permission: string): [string, string] {
  const [resource, action = ''] = permission.split(':')
  const area: Record<string, string> = {
    loan: 'Loans',
    staff: 'Team',
    role: 'Roles',
    customer: 'Customers',
    settings: 'Settings',
    payment: 'Payments',
    report: 'Reports',
  }
  const nice = action.replace(/_/g, ' ')
  return [area[resource] ?? resource.replace(/_/g, ' '), nice.charAt(0).toUpperCase() + nice.slice(1)]
}

export function ProfilePage() {
  const { staff, token, refreshProfile, logout } = useAuth()
  const { pinned, togglePinned } = useSidebarPin()
  const [fullName, setFullName] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [color, setColor] = useState<string>(AVATAR_COLORS[0].id)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  useEffect(() => {
    if (!staff) return
    setFullName(staff.full_name)
    setJobTitle(staff.job_title ?? '')
    setColor(staff.avatar_color ?? AVATAR_COLORS[0].id)
  }, [staff])

  useEffect(() => {
    if (notice?.tone !== 'ok') return
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  const permissionGroups = useMemo(() => {
    const groups = new Map<string, string[]>()
    for (const p of staff?.permissions ?? []) {
      const [area, action] = describePermission(p)
      groups.set(area, [...(groups.get(area) ?? []), action])
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [staff?.permissions])

  if (!staff) return null

  const nameError = fullName.trim().length < 2 ? 'Enter your full name.' : ''
  const dirty =
    fullName.trim() !== staff.full_name ||
    jobTitle.trim() !== (staff.job_title ?? '') ||
    color !== (staff.avatar_color ?? AVATAR_COLORS[0].id)

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || nameError || !dirty) return
    setSaving(true)
    setNotice(null)
    try {
      await adminAuthApi.updateMe(token, { full_name: fullName.trim(), job_title: jobTitle.trim(), avatar_color: color })
      await refreshProfile()
      setNotice({ tone: 'ok', text: 'Profile saved.' })
    } catch (err) {
      setNotice({ tone: 'error', text: err instanceof ApiError ? err.message : 'Could not save your profile.' })
    } finally {
      setSaving(false)
    }
  }

  const preview = { full_name: fullName || staff.full_name, avatar_color: color }

  return (
    <AdminLayout title="My profile" subtitle="How you appear to colleagues, and your preferences">
      <div className="max-w-4xl space-y-5">
        <DashCard className="p-6 flex flex-wrap items-center gap-5">
          <StaffAvatar staff={preview} size="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold text-slate-900 truncate">{preview.full_name}</h2>
            <p className="text-[13px] text-slate-500 mt-0.5">
              {[jobTitle.trim() || null, staff.role?.name ?? (staff.is_super_admin ? 'Super admin' : 'No role')]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <div className="flex flex-wrap gap-2 mt-3">
              <span
                className={clsx(
                  'inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-md capitalize',
                  staff.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600',
                )}
              >
                <span className={clsx('h-1.5 w-1.5 rounded-full', staff.status === 'active' ? 'bg-emerald-500' : 'bg-slate-400')} />
                {staff.status}
              </span>
              {staff.is_super_admin && (
                <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-[#1b2f6b]/10 text-[#1b2f6b]">
                  <ShieldCheck className="h-3 w-3" />
                  Super admin
                </span>
              )}
            </div>
          </div>
        </DashCard>

        <div className="grid lg:grid-cols-5 gap-5">
          <DashCard className="p-6 lg:col-span-3">
            <CardTitle icon={<UserRound className="h-4 w-4" />} title="Profile details" hint="Shown in the sidebar and on actions you take." />
            <form onSubmit={save} className="space-y-4 mt-5">
              <label className="block">
                <span className="block text-[12px] font-medium text-slate-700 mb-1.5">Full name</span>
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} className={input} />
                {nameError && <span className="block text-[11px] text-rose-600 mt-1">{nameError}</span>}
              </label>
              <label className="block">
                <span className="block text-[12px] font-medium text-slate-700 mb-1.5">Job title</span>
                <input
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  maxLength={100}
                  placeholder="e.g. Senior Loan Officer, Lagos Main"
                  className={input}
                />
              </label>
              <fieldset>
                <legend className="block text-[12px] font-medium text-slate-700 mb-2">Avatar colour</legend>
                <div className="flex flex-wrap gap-2">
                  {AVATAR_COLORS.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setColor(c.id)}
                      aria-pressed={color === c.id}
                      aria-label={c.label}
                      title={c.label}
                      className={clsx(
                        'h-8 w-8 rounded-lg flex items-center justify-center transition-shadow',
                        c.className,
                        color === c.id ? 'ring-2 ring-offset-2 ring-slate-400' : 'hover:ring-2 hover:ring-offset-2 hover:ring-slate-200',
                      )}
                    >
                      {color === c.id && <Check className="h-4 w-4 text-white" />}
                    </button>
                  ))}
                </div>
              </fieldset>
              <div className="flex items-center gap-3 pt-2">
                <button
                  type="submit"
                  disabled={saving || !dirty || !!nameError}
                  className="px-5 py-2.5 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold hover:bg-[#141f45] disabled:opacity-40"
                >
                  {saving ? 'Saving…' : 'Save changes'}
                </button>
                {notice && (
                  <p className={clsx('text-[13px] font-medium', notice.tone === 'ok' ? 'text-emerald-700' : 'text-rose-600')}>
                    {notice.text}
                  </p>
                )}
              </div>
            </form>
          </DashCard>

          <div className="lg:col-span-2 space-y-5">
            <DashCard className="p-6">
              <CardTitle icon={<KeyRound className="h-4 w-4" />} title="Sign-in details" />
              <dl className="mt-4 space-y-3 text-[13px]">
                <div>
                  <dt className="text-[11px] text-slate-400">Email</dt>
                  <dd className="text-slate-800 break-all">{staff.email}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-slate-400">Phone (sign-in codes go here)</dt>
                  <dd className="text-slate-800 tabular-nums">{staff.phone}</dd>
                </div>
              </dl>
              <p className="text-[11px] text-slate-400 mt-4 leading-relaxed">
                For security, an administrator changes these on the Team page.
              </p>
            </DashCard>

            <DashCard className="p-6">
              <CardTitle icon={<PanelLeft className="h-4 w-4" />} title="Preferences" />
              <label className="mt-4 flex items-start justify-between gap-4 cursor-pointer">
                <span>
                  <span className="block text-[13px] text-slate-800">Keep sidebar open</span>
                  <span className="block text-[11px] text-slate-400">Off: a slim rail that opens when you hover it.</span>
                </span>
                <Toggle on={pinned} onChange={togglePinned} label="Keep sidebar open" />
              </label>
              <button
                type="button"
                onClick={logout}
                className="mt-5 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold text-rose-600 ring-1 ring-rose-200 hover:bg-rose-50"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </DashCard>
          </div>
        </div>

        <DashCard className="p-6">
          <CardTitle
            icon={<ShieldCheck className="h-4 w-4" />}
            title={`What you can do${staff.role ? ` as ${staff.role.name}` : ''}`}
            hint={staff.role?.description ?? (staff.is_super_admin ? 'Super admins have every permission.' : undefined)}
          />
          {permissionGroups.length === 0 ? (
            <p className="text-[13px] text-slate-400 mt-4">No permissions yet. Ask an administrator to assign you a role.</p>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-5">
              {permissionGroups.map(([area, actions]) => (
                <div key={area}>
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">{area}</p>
                  <ul className="mt-1.5 space-y-1">
                    {actions.map((a) => (
                      <li key={a} className="flex items-center gap-2 text-[13px] text-slate-700">
                        <Check className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </DashCard>
        <SessionTimeoutCard scope="personal" />
      </div>
    </AdminLayout>
  )
}

const input =
  'w-full text-[13px] ring-1 ring-slate-200 rounded-lg px-3 py-2.5 bg-white focus:ring-[#1b2f6b]/40 outline-none'

function CardTitle({ icon, title, hint }: { icon: React.ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="h-8 w-8 rounded-lg bg-slate-100 text-[#1b2f6b] flex items-center justify-center shrink-0">{icon}</span>
      <div>
        <h3 className="text-[15px] font-semibold text-slate-900">{title}</h3>
        {hint && <p className="text-[12px] text-slate-400 mt-0.5">{hint}</p>}
      </div>
    </div>
  )
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onChange}
      className={clsx('relative h-6 w-11 rounded-full transition-colors shrink-0', on ? 'bg-[#1b2f6b]' : 'bg-slate-300')}
    >
      <span className={clsx('absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform', on ? 'translate-x-5' : 'translate-x-0.5')} />
    </button>
  )
}
