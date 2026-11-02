import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  GitBranch,
  GripVertical,
  Plus,
  Save,
  Shield,
  Trash2,
  Upload,
} from 'lucide-react'
import clsx from 'clsx'
import { AdminLayout } from '../components/AdminLayout'
import { PermissionGate } from '../components/PermissionGate'
import { CreateProductDialog } from '../components/products/CreateProductDialog'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { hasPermission } from '../lib/permissions'
import { getProductMeta } from '../lib/productMeta'
import {
  loansApi,
  type LoanProduct,
  type Role,
  type Workflow,
  type WorkflowStageInput,
} from '../lib/loansApi'

interface DraftStage extends WorkflowStageInput {
  key: string
}

function newStage(): DraftStage {
  return { key: crypto.randomUUID(), name: '', approver_role_id: '' }
}

function stagesToPayload(stages: DraftStage[]): WorkflowStageInput[] {
  return stages
    .filter((s) => s.name.trim() && s.approver_role_id)
    .map(({ name, slug, description, approver_role_id }) => ({
      name: name.trim(),
      slug,
      description,
      approver_role_id,
    }))
}

export function LoanProductsPage() {
  return (
    <PermissionGate permission="loan:read">
      <LoanProductsPageContent />
    </PermissionGate>
  )
}

function LoanProductsPageContent() {
  const { token, staff } = useAuth()
  const canConfigure = hasPermission(staff, 'loan:configure_workflow')
  const [products, setProducts] = useState<LoanProduct[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [stages, setStages] = useState<DraftStage[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [productNotice, setProductNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)

  const roleNameById = useMemo(
    () => Object.fromEntries(roles.map((r) => [r.id, r.name])),
    [roles],
  )

  const loadProducts = useCallback(async () => {
    if (!token) return
    const [prods, roleList] = await Promise.all([
      loansApi.listProducts(token),
      loansApi.listRoles(token),
    ])
    // All products, including switched-off ones: a new product needs its pipeline built here
    // before it can be switched on.
    setProducts(prods)
    setRoles(roleList)
    if (!selectedCode && prods.length) setSelectedCode((prods.find((p) => p.is_active) ?? prods[0]).code)
  }, [token, selectedCode])

  const loadWorkflow = useCallback(async (code: string) => {
    if (!token) return
    const active = await loansApi.getActiveWorkflow(token, code)
    setActiveWorkflow(active)
    if (active) {
      setStages(
        active.stages.map((s) => ({
          key: s.id,
          name: s.name,
          slug: s.slug,
          description: s.description ?? undefined,
          approver_role_id: s.approver_role_id,
        })),
      )
    } else {
      setStages([newStage()])
    }
    setDraftId(null)
    setMessage('')
    setError('')
  }, [token])

  useEffect(() => {
    loadProducts().finally(() => setLoading(false))
  }, [loadProducts])

  useEffect(() => {
    if (selectedCode) loadWorkflow(selectedCode)
    setProductNotice(null)
  }, [selectedCode, loadWorkflow])

  const setActive = async (product: LoanProduct, isActive: boolean) => {
    if (!token) return
    setSwitching(true)
    setProductNotice(null)
    try {
      const updated = await loansApi.setProductActive(token, product.code, isActive)
      setProducts((prev) => prev.map((p) => (p.code === updated.code ? { ...p, ...updated } : p)))
      setProductNotice({
        tone: 'ok',
        text: updated.is_active ? `${updated.name} is live for customers.` : `${updated.name} is switched off.`,
      })
    } catch (e) {
      setProductNotice({ tone: 'error', text: e instanceof ApiError ? e.message : 'Could not update the product.' })
    } finally {
      setSwitching(false)
    }
  }

  const validStages = stagesToPayload(stages)
  const hasValidStages = validStages.length > 0

  const isDirty = useMemo(() => {
    if (!activeWorkflow) return stages.length > 0
    const activeKey = activeWorkflow.stages
      .map((s) => `${s.name}|${s.approver_role_id}`)
      .join(';;')
    const draftKey = validStages.map((s) => `${s.name}|${s.approver_role_id}`).join(';;')
    return activeKey !== draftKey || draftId !== null
  }, [activeWorkflow, validStages, stages.length, draftId])

  const moveStage = (index: number, dir: -1 | 1) => {
    const next = [...stages]
    const target = index + dir
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    setStages(next)
    setMessage('')
  }

  const persistDraft = async (): Promise<string | null> => {
    if (!token || !selectedCode) return null
    const payload = stagesToPayload(stages)
    if (payload.length === 0) {
      setError('Add at least one stage with a name and approver role.')
      return null
    }

    let workflow: Workflow
    if (draftId) {
      workflow = await loansApi.updateWorkflowStages(token, draftId, payload)
    } else {
      workflow = await loansApi.createWorkflow(token, selectedCode, payload)
      setDraftId(workflow.id)
    }
    return workflow.id
  }

  const saveDraft = async () => {
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const id = await persistDraft()
      if (id) setMessage('Draft saved. Publish when ready to apply to new applications.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const publish = async () => {
    if (!token || !selectedCode) return
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const id = await persistDraft()
      if (!id) return
      const published = await loansApi.publishWorkflow(token, id)
      setMessage(`Published v${published.version}. New applications will use this pipeline.`)
      setDraftId(null)
      await loadWorkflow(selectedCode)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Publish failed')
    } finally {
      setSaving(false)
    }
  }

  const startNewVersion = () => {
    setDraftId(null)
    if (activeWorkflow) {
      setStages(
        activeWorkflow.stages.map((s) => ({
          key: crypto.randomUUID(),
          name: s.name,
          slug: s.slug,
          description: s.description ?? undefined,
          approver_role_id: s.approver_role_id,
        })),
      )
    } else {
      setStages([newStage()])
    }
    setMessage('New draft started from the active pipeline.')
    setError('')
  }

  const selected = products.find((p) => p.code === selectedCode)
  const meta = selected ? getProductMeta(selected.code) : null
  const Icon = meta?.icon

  const previewLabel = draftId || isDirty ? 'Draft preview' : 'Published pipeline'
  const previewCount = validStages.length

  return (
    <AdminLayout
      title="Loan products"
      subtitle="Create products and configure their approval pipelines"
    >
      <div className="mb-6 p-4 rounded-xl bg-white ring-1 ring-slate-200/90 flex items-start gap-3 max-w-2xl">
        <div className="h-10 w-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0">
          <Shield className="h-5 w-5 text-[#1b2f6b]" />
        </div>
        <div>
          <p className="text-[13px] font-semibold text-slate-800">Version-safe workflows</p>
          <p className="text-[12px] text-slate-500 mt-1 leading-relaxed">
            Edits below update the preview immediately. Save draft, then publish — only new applications pick up changes.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="grid lg:grid-cols-12 gap-6 animate-pulse">
          <div className="lg:col-span-4 h-80 bg-slate-100 rounded-xl" />
          <div className="lg:col-span-8 h-80 bg-slate-100 rounded-xl" />
        </div>
      ) : (
        <div className="grid lg:grid-cols-12 gap-6">
          <div className="lg:col-span-4 space-y-3">
            <div className="flex items-center justify-between px-1">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">Products</p>
              {canConfigure && (
                <button
                  type="button"
                  onClick={() => setCreating(true)}
                  className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-white bg-[#1b2f6b] hover:bg-[#141f45] px-3 py-1.5 rounded-lg transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New product
                </button>
              )}
            </div>
            {products.map((p) => {
              const pm = getProductMeta(p.code)
              const PIcon = pm.icon
              const isActive = selectedCode === p.code
              return (
                <button
                  key={p.code}
                  type="button"
                  onClick={() => setSelectedCode(p.code)}
                  className={clsx(
                    'w-full text-left p-4 rounded-xl border transition-all duration-200 bg-white',
                    isActive
                      ? 'border-[#1b2f6b]/30 ring-1 ring-[#1b2f6b]/10 shadow-sm'
                      : 'border-slate-200/90 hover:border-slate-300',
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="h-11 w-11 rounded-xl bg-slate-100 ring-1 ring-slate-200 flex items-center justify-center shrink-0">
                      <PIcon className={clsx('h-5 w-5', pm.accent)} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-slate-900 text-[14px]">{p.name}</p>
                      <p className="text-[11px] text-slate-400 mt-0.5 font-mono">{p.code}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className={clsx('text-[10px] font-semibold px-2 py-0.5 rounded-md', pm.soft, pm.accent)}>
                          {pm.label}
                        </span>
                        <span className="text-[10px] text-slate-400">{p.interest_rate_pct_monthly}% {p.interest_method === 'one_off' ? 'once' : '/ mo'}</span>
                        {!p.is_active && (
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-slate-100 text-slate-500">Off</span>
                        )}
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>

          <div className="lg:col-span-8 space-y-5">
            {selected && meta && Icon && (
              <>
                <div className="dash-card overflow-hidden">
                  <div className="h-1 bg-[#1b2f6b]" />
                  <div className="p-6">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <div className="h-12 w-12 rounded-xl bg-slate-100 ring-1 ring-slate-200 flex items-center justify-center">
                          <Icon className={clsx('h-6 w-6', meta.accent)} />
                        </div>
                        <div>
                          <h3 className="text-lg font-semibold text-slate-900">{selected.name}</h3>
                          <p className="text-[13px] text-slate-500 mt-0.5 max-w-lg">{selected.description}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {canConfigure && (
                          <button
                            type="button"
                            disabled={switching}
                            onClick={() => setActive(selected, !selected.is_active)}
                            className={clsx(
                              'text-[11px] font-semibold px-2.5 py-1 rounded-md ring-1 transition-colors disabled:opacity-50',
                              selected.is_active
                                ? 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50'
                                : 'bg-[#1b2f6b] text-white ring-[#1b2f6b] hover:bg-[#141f45]',
                            )}
                          >
                            {selected.is_active ? 'Switch off' : 'Switch on'}
                          </button>
                        )}
                        {activeWorkflow && (
                          <span className="text-[11px] font-medium text-slate-500 bg-slate-100 px-2.5 py-1 rounded-md">
                            Live v{activeWorkflow.version}
                          </span>
                        )}
                        <span
                          className={clsx(
                            'inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-md',
                            isDirty || draftId
                              ? 'bg-amber-50 text-amber-800 ring-1 ring-amber-200'
                              : 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200',
                          )}
                        >
                          <GitBranch className="h-3 w-3" />
                          {previewLabel} · {previewCount} stage{previewCount === 1 ? '' : 's'}
                        </span>
                      </div>
                    </div>

                    {!selected.is_active && !productNotice && (
                      <p className="mt-4 text-[12px] text-amber-800 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-3 py-2">
                        {activeWorkflow
                          ? 'Switched off: customers can’t see this product. Switch it on when you’re ready.'
                          : 'Switched off. Build and publish its approval pipeline below, then switch it on.'}
                      </p>
                    )}
                    {productNotice && (
                      <p
                        className={clsx(
                          'mt-4 text-[12px] rounded-lg px-3 py-2 ring-1',
                          productNotice.tone === 'ok'
                            ? 'text-emerald-800 bg-emerald-50 ring-emerald-200'
                            : 'text-rose-700 bg-rose-50 ring-rose-200',
                        )}
                      >
                        {productNotice.text}
                      </p>
                    )}

                    {previewCount > 0 ? (
                      <div className="mt-6 overflow-x-auto pb-2">
                        <div className="flex items-center gap-0 min-w-max">
                          {validStages.map((stage, i) => (
                            <div key={`${stage.name}-${i}`} className="flex items-center">
                              <div className="flex flex-col items-center w-[120px]">
                                <div className="h-10 w-10 rounded-full flex items-center justify-center text-[13px] font-bold bg-slate-100 text-[#1b2f6b] ring-4 ring-white shadow-sm">
                                  {i + 1}
                                </div>
                                <p className="text-[11px] font-semibold text-slate-700 mt-2 text-center leading-tight px-1">
                                  {stage.name}
                                </p>
                                <p className="text-[10px] text-slate-400 mt-0.5 text-center truncate w-full px-1">
                                  {roleNameById[stage.approver_role_id] ?? 'Role'}
                                </p>
                              </div>
                              {i < validStages.length - 1 && (
                                <div className="w-8 h-0.5 pipeline-connector rounded-full mx-1 shrink-0" />
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="mt-6 text-[13px] text-slate-400 italic">
                        No valid stages yet — add a name and approver role below.
                      </p>
                    )}
                  </div>
                </div>

                <div className="dash-card p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
                    <div>
                      <h3 className="text-[15px] font-semibold text-slate-900">Stage editor</h3>
                      <p className="text-[12px] text-slate-400 mt-0.5">
                        {canConfigure
                          ? 'Changes appear in the preview above as you edit'
                          : 'View-only — you need workflow configure permission to edit'}
                      </p>
                    </div>
                    {canConfigure && (
                      <button
                        type="button"
                        onClick={startNewVersion}
                        className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#1b2f6b] px-3 py-2 rounded-lg hover:bg-slate-100 transition-colors"
                      >
                        <GitBranch className="h-3.5 w-3.5" />
                        Reset from published
                      </button>
                    )}
                  </div>

                  <div className="space-y-3">
                    {stages.map((stage, index) => (
                      <div
                        key={stage.key}
                        className="stage-card flex gap-3 items-start p-4 rounded-xl ring-1 ring-slate-200/80"
                      >
                        <div className="flex flex-col items-center gap-1 pt-1">
                          <GripVertical className="h-4 w-4 text-slate-300" />
                          <span className="h-7 w-7 rounded-lg flex items-center justify-center text-[12px] font-bold bg-slate-100 text-[#1b2f6b]">
                            {index + 1}
                          </span>
                        </div>
                        <div className="flex-1 grid sm:grid-cols-2 gap-3">
                          <input
                            value={stage.name}
                            onChange={(e) => {
                              if (!canConfigure) return
                              const next = [...stages]
                              next[index] = { ...next[index], name: e.target.value }
                              setStages(next)
                              setMessage('')
                            }}
                            disabled={!canConfigure}
                            placeholder="Stage name e.g. Credit review"
                            className="text-[13px] ring-1 ring-slate-200 rounded-lg px-3 py-2.5 bg-white focus:ring-[#1b2f6b]/30 outline-none disabled:bg-slate-50 disabled:text-slate-500"
                          />
                          <select
                            value={stage.approver_role_id}
                            onChange={(e) => {
                              if (!canConfigure) return
                              const next = [...stages]
                              next[index] = { ...next[index], approver_role_id: e.target.value }
                              setStages(next)
                              setMessage('')
                            }}
                            disabled={!canConfigure}
                            className="text-[13px] ring-1 ring-slate-200 rounded-lg px-3 py-2.5 bg-white focus:ring-[#1b2f6b]/30 outline-none disabled:bg-slate-50 disabled:text-slate-500"
                          >
                            <option value="">Select approver role</option>
                            {roles.map((r) => (
                              <option key={r.id} value={r.id}>{r.name}</option>
                            ))}
                          </select>
                        </div>
                        {canConfigure && (
                          <>
                            <div className="flex flex-col gap-0.5">
                              <button type="button" onClick={() => moveStage(index, -1)} className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100">
                                <ChevronUp className="h-4 w-4" />
                              </button>
                              <button type="button" onClick={() => moveStage(index, 1)} className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100">
                                <ChevronDown className="h-4 w-4" />
                              </button>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setStages(stages.filter((_, i) => i !== index))
                                setMessage('')
                              }}
                              className="p-2 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    ))}
                  </div>

                  {canConfigure && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setStages([...stages, newStage()])
                          setMessage('')
                        }}
                        className="mt-4 inline-flex items-center gap-2 text-[13px] font-semibold text-[#1b2f6b] px-3 py-2 rounded-lg hover:bg-slate-100 transition-colors"
                      >
                        <Plus className="h-4 w-4" />
                        Add stage
                      </button>

                      <div className="flex flex-wrap items-center gap-3 mt-6 pt-6 border-t border-slate-100">
                        <button
                          type="button"
                          disabled={saving || !hasValidStages}
                          onClick={saveDraft}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-800 text-white text-[13px] font-semibold hover:bg-slate-900 disabled:opacity-50 transition-colors"
                        >
                          <Save className="h-4 w-4" />
                          Save draft
                        </button>
                        <button
                          type="button"
                          disabled={saving || !hasValidStages}
                          onClick={publish}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#1b2f6b] text-white text-[13px] font-semibold hover:bg-[#141f45] disabled:opacity-50 transition-colors"
                        >
                          <Upload className="h-4 w-4" />
                          Save & publish
                        </button>
                        {message && (
                          <p className="text-[13px] text-emerald-700 font-medium">{message}</p>
                        )}
                        {error && (
                          <p className="text-[13px] text-rose-600 font-medium flex items-center gap-1.5">
                            <AlertCircle className="h-4 w-4" />
                            {error}
                          </p>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
            )}

      <CreateProductDialog
        open={creating}
        existingCodes={products.map((p) => p.code)}
        onClose={() => setCreating(false)}
        onCreate={async (input) => {
          if (!token) throw new Error('Signed out')
          const created = await loansApi.createProduct(token, input)
          setProducts((prev) => [...prev, created])
          setSelectedCode(created.code)
          return created
        }}
      />
    </AdminLayout>
  )
}
