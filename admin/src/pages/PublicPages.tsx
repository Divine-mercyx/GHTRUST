import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2, Mail, MessageCircle, Phone } from 'lucide-react'
import { API_BASE } from '../lib/api'

/**
 * Public pages for the app stores: the Privacy Policy URL, Terms of Use and the Support URL
 * App Store Connect and Google Play ask for. The text is the same documents the app shows
 * (GET /api/v1/legal/{slug}), so there is one copy to keep up to date. No staff session.
 */

interface LegalDocument {
  title: string
  version: string
  effective_date: string
  draft: boolean
  sections: { heading: string; body: string }[]
}

interface Support {
  phone: string | null
  email: string | null
  whatsapp: string | null
  hours: string | null
}

function Shell({ subtitle, children }: { subtitle: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="GH Trust" className="h-10 w-10 rounded-lg border border-slate-200 bg-white p-1" />
          <div>
            <p className="text-sm font-bold text-navy tracking-tight">GH Trust</p>
            <p className="text-xs text-slate-500">{subtitle}</p>
          </div>
        </div>
        {children}
        <nav className="flex flex-wrap gap-4 text-[13px] text-slate-500">
          <Link to="/privacy" className="hover:text-navy">Privacy Policy</Link>
          <Link to="/terms" className="hover:text-navy">Terms of Use</Link>
          <Link to="/help" className="hover:text-navy">Help & contact</Link>
          <Link to="/delete-account" className="hover:text-navy">Delete your account</Link>
        </nav>
      </div>
    </div>
  )
}

function useJson<T>(path: string): { data: T | null; failed: boolean } {
  const [data, setData] = useState<T | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    setData(null)
    setFailed(false)
    fetch(`${API_BASE}/api/v1${path}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((body: T) => live && setData(body))
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [path])
  return { data, failed }
}

function Loading({ failed }: { failed: boolean }) {
  return (
    <div className="dash-card p-6 text-[14px] text-slate-600">
      {failed ? (
        "We couldn't load this page. Please refresh, or try again in a few minutes."
      ) : (
        <span className="inline-flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </span>
      )}
    </div>
  )
}

export function LegalPage({ slug }: { slug: 'privacy' | 'terms' }) {
  const { data, failed } = useJson<LegalDocument>(`/legal/${slug}`)
  const subtitle = slug === 'privacy' ? 'Privacy Policy' : 'Terms of Use'
  useEffect(() => {
    document.title = `${subtitle} | GH Trust`
  }, [subtitle])
  return (
    <Shell subtitle={subtitle}>
      {data ? (
        <article className="dash-card p-6 space-y-5">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{data.title}</h1>
            <p className="text-[13px] text-slate-500">Effective {data.effective_date}</p>
          </div>
          {data.draft ? (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-[13px] text-amber-800">Draft wording, pending final legal review.</p>
          ) : null}
          {data.sections.map((section) => (
            <section key={section.heading} className="space-y-1.5">
              <h2 className="text-[15px] font-semibold text-slate-900">{section.heading}</h2>
              <p className="text-[14px] leading-relaxed text-slate-700 whitespace-pre-line">{section.body}</p>
            </section>
          ))}
        </article>
      ) : (
        <Loading failed={failed} />
      )}
    </Shell>
  )
}

export function HelpPage() {
  const { data, failed } = useJson<{ support: Support }>('/app/config?platform=ios')
  const support = data?.support
  useEffect(() => {
    document.title = 'Help & contact | GH Trust'
  }, [])
  return (
    <Shell subtitle="Help & contact">
      {support ? (
        <div className="dash-card p-6 space-y-4">
          <h1 className="text-xl font-bold text-slate-900">Contact GH Trust</h1>
          <p className="text-[14px] text-slate-600">
            Questions about your account, a loan, a payment or the app? Message us in the app (Profile → Help &
            support), or contact us here.
          </p>
          <ul className="space-y-3 text-[14px] text-slate-800">
            {support.email ? (
              <li className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-navy" />
                <a href={`mailto:${support.email}`} className="text-navy underline">{support.email}</a>
              </li>
            ) : null}
            {support.phone ? (
              <li className="flex items-center gap-2">
                <Phone className="h-4 w-4 text-navy" />
                <a href={`tel:${support.phone}`} className="text-navy underline">{support.phone}</a>
              </li>
            ) : null}
            {support.whatsapp ? (
              <li className="flex items-center gap-2">
                <MessageCircle className="h-4 w-4 text-navy" />
                <a href={`https://wa.me/${support.whatsapp}`} className="text-navy underline">WhatsApp +{support.whatsapp}</a>
              </li>
            ) : null}
          </ul>
          {support.hours ? <p className="text-[13px] text-slate-500">{support.hours}</p> : null}
          <p className="text-[13px] text-slate-500">
            To delete your account, use Profile → Delete account in the app, or{' '}
            <Link to="/delete-account" className="text-navy underline">delete it here</Link>.
          </p>
        </div>
      ) : (
        <Loading failed={failed} />
      )}
    </Shell>
  )
}
