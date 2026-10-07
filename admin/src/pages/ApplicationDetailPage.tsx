import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Banknote,
  Check,
  Clock,
  Download,
  FileText,
  ExternalLink,
  MapPin,
  Target,
  User,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { AdminLayout } from '../components/AdminLayout'
import { WorkflowPipeline } from '../components/WorkflowPipeline'
import { PermissionGate } from '../components/PermissionGate'
import { StatusPill } from '../components/ui'
import { useAuth } from '../lib/auth'
import { hasPermission } from '../lib/permissions'
import { getProductMeta, initials } from '../lib/productMeta'
import {
  formatDuration,
  formatNaira,
  loansApi,
  type ApplicationDetail,
  type ApplicationWorkflowState,
  type AuditLogEntry,
} from '../lib/loansApi'

export function ApplicationDetailPage() {
  return (
    <PermissionGate permission="loan:read">
      <ApplicationDetailContent />
    </PermissionGate>
  )
}

function ApplicationDetailContent() {
  const { id } = useParams<{ id: string }>()
  const { token, staff } = useAuth()
  const [app, setApp] = useState<ApplicationDetail | null>(null)
  const [workflow, setWorkflow] = useState<ApplicationWorkflowState | null>(null)
  const [audit, setAudit] = useState<AuditLogEntry[]>([])
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [docError, setDocError] = useState('')
  const [verifyingDocId, setVerifyingDocId] = useState<string | null>(null)
  const [downloadingDocId, setDownloadingDocId] = useState<string | null>(null)

  const canReview = hasPermission(staff, 'loan:review')
  const canDisburse = hasPermission(staff, 'loan:disburse')
  const canVerifyDocs = hasPermission(staff, 'loan:verify_documents')

  const load = useCallback(async () => {
    if (!token || !id) return
    setLoading(true)
    try {
      const [detail, wf, logs] = await Promise.all([
        loansApi.getApplication(token, id),
        loansApi.getWorkflowState(token, id),
        loansApi.getAuditLog(token, id),
      ])
      setApp(detail)
      setWorkflow(wf)
      setAudit(logs)
    } finally {
      setLoading(false)
    }
  }, [token, id])

  useEffect(() => { load() }, [load])

  const act = async (action: 'approved' | 'rejected') => {
    if (!token || !id) return
    setActing(true)
    try {
      await loansApi.stageAction(token, id, action, note || undefined)
      setNote('')
      await load()
    } finally {
      setActing(false)
    }
  }

  const disburse = async () => {
    if (!token || !id) return
    setActing(true)
    try {
      await loansApi.disburse(token, id, note || 'Disbursed')
      setNote('')
      await load()
    } finally {
      setActing(false)
    }
  }

  const verifyDoc = async (docId: string, status: 'verified' | 'rejected') => {
    if (!token || !id) return
    setDocError('')
    setVerifyingDocId(docId)
    try {
      const updated = await loansApi.verifyDocument(token, id, docId, status)
      setApp(updated)
      await load()
    } catch (e) {
      setDocError(e instanceof Error ? e.message : 'Document verification failed')
    } finally {
      setVerifyingDocId(null)
    }
  }

  const downloadDoc = async (docId: string, fileName: string) => {
    if (!token || !id) return
    setDocError('')
    setDownloadingDocId(docId)
    try {
      await loansApi.downloadDocument(token, id, docId, fileName)
    } catch (e) {
      setDocError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setDownloadingDocId(null)
    }
  }

  if (loading || !app) {
    return (
      <AdminLayout title="Application detail">
        <div className="flex items-center justify-center py-24">
          <div className="h-10 w-10 rounded-full border-2 border-slate-200 border-t-[#1b2f6b] animate-spin" />
        </div>
      </AdminLayout>
    )
  }

  const name = (app.universal_form?.full_name as string) ?? 'Applicant'
  const meta = getProductMeta(app.product_code)
  const Icon = meta.icon
  const canAct = canReview && app.status === 'under_review' && workflow?.current_stage
  const canDisburseNow = canDisburse && app.status === 'approved'

  return (
    <AdminLayout title={name} subtitle={`${app.product_name} · ${app.id.slice(0, 8)}…`}>
      <Link
        to="/applications"
        className="inline-flex items-center gap-1.5 text-[13px] font-medium text-slate-500 hover:text-[#1b2f6b] mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to applications
      </Link>

      {/* Hero */}
      <div className="dash-card overflow-hidden mb-6">
        <div className="h-2 bg-[#1b2f6b]" />
        <div className="p-6 lg:p-8">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div className="flex items-start gap-4">
              <div className="h-16 w-16 rounded-2xl flex items-center justify-center text-lg font-bold bg-slate-100 text-[#1b2f6b] ring-1 ring-slate-200">
                {initials(name)}
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-2xl font-semibold text-slate-900 tracking-tight">{name}</h2>
                  <StatusPill status={app.status} />
                </div>
                <div className="flex flex-wrap items-center gap-3 mt-2">
                  <span className={clsx('inline-flex items-center gap-1.5 text-[12px] font-semibold px-2.5 py-1 rounded-md', meta.soft, meta.accent)}>
                    <Icon className="h-3.5 w-3.5" />
                    {app.product_name}
                  </span>
                  <span className="text-[12px] text-slate-400 flex items-center gap-1">
                    <MapPin className="h-3.5 w-3.5" />
                    {app.branch}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-3 mt-3">
                  <Link
                    to={`/customers/${app.customer_id}`}
                    className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#1b2f6b] bg-[#1b2f6b]/5 hover:bg-[#1b2f6b]/10 px-3 py-1.5 rounded-lg ring-1 ring-[#1b2f6b]/15 transition-colors"
                  >
                    <User className="h-3.5 w-3.5" />
                    View customer
                    <ExternalLink className="h-3 w-3 opacity-60" />
                  </Link>
                  {app.account_number && (
                    <span className="text-[12px] text-slate-500">
                      CASA: <span className="font-mono font-semibold text-[#1b2f6b]">{app.account_number}</span>
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="text-right">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">Requested amount</p>
              <p className="text-3xl font-bold text-slate-900 tabular-nums mt-1">{formatNaira(app.requested_amount)}</p>
              {workflow?.processing_duration_seconds != null && (
                <p className="text-[12px] text-slate-400 mt-2 flex items-center justify-end gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {formatDuration(workflow.processing_duration_seconds)} in pipeline
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-6">
          {/* Application details */}
          <div className="dash-card p-6">
            <h3 className="text-[14px] font-semibold text-slate-900 mb-4">Application details</h3>
            <div className="grid sm:grid-cols-2 gap-4">
              {[
                { icon: Target, label: 'Purpose', value: (app.universal_form?.purpose as string) ?? '—' },
                { icon: Banknote, label: 'Monthly income', value: formatNaira(app.universal_form?.monthly_income as string) },
                { icon: User, label: 'Repayment period', value: (app.universal_form?.repayment_period as string) ?? '—' },
                { icon: FileText, label: 'Source of repayment', value: (app.universal_form?.source_of_repayment as string) ?? '—' },
              ].map((item) => (
                <div key={item.label} className="flex items-start gap-3 p-4 rounded-xl bg-slate-50/80 ring-1 ring-slate-100">
                  <div className="h-9 w-9 rounded-lg bg-white ring-1 ring-slate-200/80 flex items-center justify-center shrink-0">
                    <item.icon className="h-4 w-4 text-slate-400" />
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{item.label}</p>
                    <p className="text-[13px] font-medium text-slate-800 mt-0.5">{item.value}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Workflow pipeline */}
          {workflow && (workflow.pipeline_stages?.length ?? 0) > 0 && (
            <div className="dash-card p-6">
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h3 className="text-[14px] font-semibold text-slate-900">Approval pipeline</h3>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    Completed stages highlighted in green · current stage in navy
                  </p>
                </div>
                {workflow.workflow_version != null && (
                  <span className="text-[11px] font-medium text-slate-400 bg-slate-100 px-2.5 py-1 rounded-md">
                    Workflow v{workflow.workflow_version}
                  </span>
                )}
              </div>

              <WorkflowPipeline
                stages={workflow.pipeline_stages.map((s) => ({
                  name: s.name,
                  status: s.status as 'completed' | 'current' | 'upcoming' | 'rejected',
                  approver_role_name: s.approver_role_name,
                }))}
              />

              {workflow.current_stage && (
                <div className="mt-5 flex items-center gap-3 p-4 rounded-xl bg-[#1b2f6b]/5 ring-1 ring-[#1b2f6b]/15">
                  <p className="text-[12px] text-slate-600">
                    <span className="font-semibold text-[#1b2f6b]">Current:</span>{' '}
                    {workflow.current_stage.name} — awaiting {workflow.current_stage.approver_role_name}
                  </p>
                </div>
              )}

              {app.status === 'offer_sent' && (
                <div className="mt-5 px-4 py-3 rounded-xl bg-amber-50 ring-1 ring-amber-200 text-[13px] text-amber-800">
                  The loan offer is with the customer. The workflow continues when they accept it in the app; if they
                  decline, it comes back to credit review. You can still correct the terms or reject the application.
                </div>
              )}

              {(canAct || canDisburseNow) && (
                <div className="mt-5 space-y-3">
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Add an optional note for the audit trail…"
                    rows={2}
                    className="w-full text-[13px] ring-1 ring-slate-200 rounded-xl px-4 py-3 bg-white outline-none focus:ring-[#1b2f6b]/30 resize-none"
                  />
                  <div className="flex flex-wrap gap-2">
                    {canAct && (
                      <>
                        <button
                          type="button"
                          disabled={acting}
                          onClick={() => act('approved')}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-emerald-600 text-white text-[13px] font-semibold hover:bg-emerald-500 disabled:opacity-50 shadow-sm transition-colors"
                        >
                          <Check className="h-4 w-4" />
                          Approve stage
                        </button>
                        <button
                          type="button"
                          disabled={acting}
                          onClick={() => act('rejected')}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-white text-rose-600 text-[13px] font-semibold ring-1 ring-rose-200 hover:bg-rose-50 disabled:opacity-50 transition-colors"
                        >
                          <X className="h-4 w-4" />
                          Reject
                        </button>
                      </>
                    )}
                    {canDisburseNow && (
                      <span
                        className={
                          app.offer_accepted_at
                            ? 'text-[12px] font-medium text-emerald-700'
                            : 'text-[12px] font-medium text-amber-700'
                        }
                      >
                        {app.offer_accepted_at
                          ? `Customer accepted the offer ${new Date(app.offer_accepted_at).toLocaleString()}`
                          : 'Waiting for the customer to accept the offer in the app'}
                      </span>
                    )}
                    {canDisburseNow && (
                      <button
                        type="button"
                        disabled={acting || !app.offer_accepted_at}
                        title={app.offer_accepted_at ? undefined : 'The customer must accept the loan offer first'}
                        onClick={disburse}
                        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold hover:bg-[#141f45] disabled:opacity-50 transition-colors"
                      >
                        Mark disbursed
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Stage history */}
          {workflow && workflow.stage_decisions.length > 0 && (
            <div className="dash-card p-6">
              <h3 className="text-[14px] font-semibold text-slate-900 mb-5">Stage history</h3>
              <div className="space-y-0">
                {workflow.stage_decisions.map((d, i) => (
                  <div key={d.id} className="flex gap-4">
                    <div className="flex flex-col items-center">
                      <div
                        className={clsx(
                          'h-8 w-8 rounded-full flex items-center justify-center shrink-0',
                          d.action === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-600',
                        )}
                      >
                        {d.action === 'approved' ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                      </div>
                      {i < workflow.stage_decisions.length - 1 && (
                        <div className="w-0.5 flex-1 min-h-[24px] bg-slate-200 my-1" />
                      )}
                    </div>
                    <div className="flex-1 pb-5">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold text-slate-900 text-[13px]">{d.stage_name}</p>
                          <p className="text-[12px] text-slate-500 mt-0.5">
                            {d.staff_name} · <span className="capitalize">{d.action}</span>
                          </p>
                          {d.note && <p className="text-[12px] text-slate-400 mt-1 italic">"{d.note}"</p>}
                        </div>
                        <span className="text-[11px] text-slate-400 tabular-nums flex items-center gap-1 shrink-0">
                          <Clock className="h-3 w-3" />
                          {formatDuration(d.duration_seconds)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Documents */}
          {app.documents.length > 0 && (
            <div className="dash-card p-6">
              <h3 className="text-[14px] font-semibold text-slate-900 mb-4">Documents</h3>
              {docError && (
                <p className="text-[12px] text-rose-600 mb-3 p-2 rounded-lg bg-rose-50">{docError}</p>
              )}
              <div className="grid sm:grid-cols-2 gap-3">
                {app.documents.map((doc) => (
                  <div key={doc.id} className="flex items-center gap-3 p-3 rounded-xl ring-1 ring-slate-200/80 bg-slate-50/50">
                    <div className="h-10 w-10 rounded-lg bg-white ring-1 ring-slate-200 flex items-center justify-center">
                      <FileText className="h-5 w-5 text-slate-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[12px] font-semibold text-slate-800 capitalize truncate">
                        {doc.document_type.replace(/_/g, ' ')}
                      </p>
                      <p className="text-[11px] text-slate-400 truncate">{doc.file_name}</p>
                    </div>
                    <div className="flex flex-col items-end gap-1.5 shrink-0">
                      <StatusPill status={doc.status} />
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          disabled={downloadingDocId === doc.id}
                          onClick={() => downloadDoc(doc.id, doc.file_name)}
                          className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-500 hover:text-[#1b2f6b] px-2 py-1 rounded-md hover:bg-white disabled:opacity-50"
                        >
                          <Download className="h-3 w-3" />
                          {downloadingDocId === doc.id ? '…' : 'Download'}
                        </button>
                        {canVerifyDocs && doc.status === 'pending' && (
                          <>
                            <button
                              type="button"
                              disabled={verifyingDocId === doc.id}
                              onClick={() => verifyDoc(doc.id, 'verified')}
                              className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-50 px-2 py-1 rounded-md disabled:opacity-50"
                            >
                              Verify
                            </button>
                            <button
                              type="button"
                              disabled={verifyingDocId === doc.id}
                              onClick={() => verifyDoc(doc.id, 'rejected')}
                              className="inline-flex items-center gap-1 text-[10px] font-semibold text-rose-600 hover:bg-rose-50 px-2 py-1 rounded-md disabled:opacity-50"
                            >
                              Reject
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Guarantors */}
          {app.guarantors.length > 0 && (
            <div className="dash-card p-6">
              <h3 className="text-[14px] font-semibold text-slate-900 mb-4">Guarantors</h3>
              <div className="space-y-2">
                {app.guarantors.map((g) => (
                  <div key={g.id} className="flex items-center gap-3 p-3 rounded-xl bg-slate-50 ring-1 ring-slate-100">
                    <div className="h-9 w-9 rounded-lg bg-slate-100 text-[#1b2f6b] flex items-center justify-center text-[11px] font-bold">
                      {initials(g.full_name)}
                    </div>
                    <div>
                      <p className="text-[13px] font-medium text-slate-800">{g.full_name}</p>
                      <p className="text-[11px] text-slate-400">{g.phone ?? 'No phone'}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Audit trail */}
        <div className="dash-card p-6 h-fit sticky top-20">
          <h3 className="text-[14px] font-semibold text-slate-900 mb-5">Audit trail</h3>
          <div className="space-y-0 max-h-[640px] overflow-y-auto pr-1">
            {audit.map((entry, i) => (
              <div key={entry.id} className="flex gap-3 pb-5">
                <div className="flex flex-col items-center">
                  <div className="h-2 w-2 rounded-full bg-[#1b2f6b] mt-1.5 shrink-0" />
                  {i < audit.length - 1 && <div className="w-px flex-1 bg-slate-200 mt-1" />}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-semibold text-slate-800 capitalize leading-snug">
                    {entry.event_type.replace(/_/g, ' ')}
                  </p>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {entry.actor_label ?? entry.actor_type}
                  </p>
                  <p className="text-[10px] text-slate-300 mt-0.5 tabular-nums">
                    {new Date(entry.created_at).toLocaleString()}
                  </p>
                  {entry.message && (
                    <p className="text-[11px] text-slate-500 mt-1.5 p-2 rounded-lg bg-slate-50">{entry.message}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AdminLayout>
  )
}
