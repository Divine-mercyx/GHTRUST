"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight, Banknote, Check, CheckCircle2, Circle, Clock, Download, ExternalLink, FileText, Send, X, XCircle,
} from "lucide-react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { DescriptionList, Field, PageHeader } from "@/components/admin/Page";
import { Empty, ErrorState, InlineError, Notice, PageSkeleton, Skeleton } from "@/components/admin/States";
import { P, useStaffAuth } from "@/lib/admin/auth";
import { applicationsApi, loansApi } from "@/lib/admin/endpoints";
import { useAction, useResource } from "@/lib/admin/hooks";
import { date, dateTime, duration, humanize, money, relativeTime, todayIso } from "@/lib/admin/format";
import { cn } from "@/lib/utils";
import type { ApplicationDetail, ApplicationWorkflowState, DocumentChecklistItem } from "@/lib/admin/types";

const TERMS_EDITABLE = ["submitted", "under_review", "documents_incomplete", "approved"];
/** Statuses where the loan amount is settled (approved_amount null means "as requested"). */
const PAST_APPROVAL = ["approved", "ready_to_disburse", "disbursed"];

export default function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const app = useResource(() => applicationsApi.get(id), [id]);
  const workflow = useResource(() => applicationsApi.workflow(id), [id]);
  const audit = useResource(() => applicationsApi.auditLog(id), [id]);
  const queue = useResource(() => applicationsApi.list({ status: "under_review", limit: 50 }), [id]);

  const reloadAll = () => {
    app.reload();
    workflow.reload();
    audit.reload();
    queue.reload();
  };

  if (app.loading && !app.data) return <PageSkeleton />;
  if (app.error) return <ErrorState message={app.error} onRetry={app.reload} />;
  const a = app.data!;
  const form = a.universal_form as Record<string, string | number | null | undefined>;

  // Next application in the review queue (wraps around), for moving through reviews quickly.
  const others = (queue.data?.items ?? []).filter((x) => x.id !== a.id);
  const idx = (queue.data?.items ?? []).findIndex((x) => x.id === a.id);
  const next = idx >= 0 ? queue.data!.items[idx + 1] ?? others[0] : others[0];

  const required = a.document_checklist.filter((d) => d.required);
  const verified = required.filter((d) => d.status === "verified").length;

  return (
    <>
      <PageHeader
        back={{ href: "/admin/loan-applications", label: "Applications" }}
        title={(form.full_name as string) ?? "Applicant"}
        meta={<StatusBadge status={a.status} />}
        description={[a.product_name, humanize(a.channel), a.branch, a.submitted_at ? `Submitted ${date(a.submitted_at)}` : null]
          .filter(Boolean)
          .join(" · ")}
        actions={
          <>
            <ButtonLink href={`/admin/customers/${a.customer_id}`} variant="outline">
              Customer profile
            </ButtonLink>
            {next && (
              <ButtonLink href={`/admin/loan-applications/${next.id}`} variant="outline" title={`Next to review: ${next.applicant_name ?? ""}`}>
                Next in queue <ArrowRight className="h-4 w-4" />
              </ButtonLink>
            )}
          </>
        }
      />

      <Card className="mb-6 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
        <Figure label="Requested" value={money(a.requested_amount)} />
        <Figure
          label={a.approved_amount || !PAST_APPROVAL.includes(a.status) ? "Approved" : "Approved (as requested)"}
          value={money(a.approved_amount ?? (PAST_APPROVAL.includes(a.status) ? a.requested_amount : null))}
          muted={!a.approved_amount && !PAST_APPROVAL.includes(a.status)}
        />
        <Figure label="Tenure" value={a.tenure_months ? `${a.tenure_months} months` : "—"} />
        <Figure
          label="Documents verified"
          value={`${verified} / ${required.length}`}
          tone={required.length > 0 && verified === required.length ? "text-success" : undefined}
        />
        <Figure label="Current stage" value={workflow.data?.current_stage?.name ?? humanize(a.status)} small />
      </Card>

      {a.rejection_reason && (
        <Notice tone="error" title="Rejected" className="mb-6">
          {a.rejection_reason}
        </Notice>
      )}

      {a.status === "offer_sent" && (
        <Notice tone="info" title="Waiting for customer" className="mb-6">
          The loan offer is with the customer after credit approval. They must accept or decline in the app before the
          workflow can continue.
        </Notice>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-12">
        <div className="min-w-0 space-y-6 xl:col-span-8">
          <DocumentsCard application={a} onChanged={reloadAll} />
          <WorkflowCard state={workflow.data} error={workflow.error} loading={workflow.loading && !workflow.data} />
          <ApplicantCard application={a} />
          <AuditCard entries={audit.data} error={audit.error} />
        </div>
        <aside className="min-w-0 space-y-6 xl:sticky xl:top-20 xl:col-span-4" aria-label="Decisions">
          <StageActionCard application={a} state={workflow.data} onChanged={reloadAll} nextHref={next ? `/admin/loan-applications/${next.id}` : undefined} />
          <DisbursementCard application={a} onChanged={reloadAll} />
          <TermsCard application={a} onChanged={reloadAll} />
        </aside>
      </div>
    </>
  );
}

function Figure({ label, value, tone, muted, small }: { label: string; value: string; tone?: string; muted?: boolean; small?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-ink-3">{label}</p>
      <p className={cn("num mt-1 truncate font-semibold", small ? "text-[15px] leading-7" : "text-lg", muted ? "text-gray-300" : tone ?? "text-ink")} title={value}>
        {value}
      </p>
    </div>
  );
}

// ── Workflow ──────────────────────────────────────────────────────────────

function WorkflowCard({ state, error, loading }: { state?: ApplicationWorkflowState; error: string | null; loading: boolean }) {
  if (error) return <ErrorState message={error} />;
  if (loading) {
    return (
      <Card>
        <Skeleton className="h-4 w-40" />
        <div className="mt-5 space-y-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      </Card>
    );
  }
  if (!state) return null;
  return (
    <Card>
      <CardHeader
        title="Approval workflow"
        description={state.processing_duration_seconds !== null ? `Total processing time ${duration(state.processing_duration_seconds)}` : undefined}
        actions={state.workflow_version ? <Badge variant="muted">Version {state.workflow_version}</Badge> : undefined}
      />
      {state.pipeline_stages.length === 0 ? (
        <Empty title="No workflow assigned yet" hint="A workflow is assigned when the customer submits." compact />
      ) : (
        <ol className="relative">
          {state.pipeline_stages.map((stage, i) => {
            const decision = state.stage_decisions.find((d) => d.stage_id === stage.id);
            const last = i === state.pipeline_stages.length - 1;
            const Icon =
              stage.status === "completed" ? CheckCircle2 : stage.status === "rejected" ? XCircle : stage.status === "current" ? Clock : Circle;
            const iconCls =
              stage.status === "completed"
                ? "text-success"
                : stage.status === "rejected"
                  ? "text-error"
                  : stage.status === "current"
                    ? "text-cyan"
                    : "text-gray-300";
            return (
              <li key={stage.id} className="relative flex gap-3 pb-5 last:pb-0">
                {!last && <span className={cn("absolute left-[9px] top-6 h-[calc(100%-20px)] w-px", stage.status === "completed" ? "bg-success/40" : "bg-line")} aria-hidden />}
                <Icon className={cn("relative mt-0.5 h-[18px] w-[18px] shrink-0 bg-white", iconCls)} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <p className={cn("text-sm font-semibold", stage.status === "upcoming" ? "text-ink-3" : "text-ink")}>{stage.name}</p>
                    {stage.status === "current" && <Badge variant="info">In progress</Badge>}
                    <span className="sr-only">({stage.status})</span>
                  </div>
                  <p className="text-xs text-ink-3">{stage.approver_role_name ?? "Any approver"}</p>
                  {decision && (
                    <p className="mt-1.5 rounded-md bg-gray-50 px-2.5 py-1.5 text-xs text-ink-2">
                      <strong className="font-semibold">{humanize(decision.action)}</strong> by {decision.staff_name ?? "staff"} ·{" "}
                      {dateTime(decision.decided_at)} · took {duration(decision.duration_seconds)}
                      {decision.note ? <span className="block text-ink-3">“{decision.note}”</span> : null}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

/** Required documents not yet verified. The API refuses final approval and disbursement while any remain. */
function unverifiedDocuments(application: ApplicationDetail): string[] {
  return application.document_checklist.filter((d) => d.required && d.status !== "verified").map((d) => d.label);
}

function OutstandingDocuments({ labels, action }: { labels: string[]; action: string }) {
  if (labels.length === 0) return null;
  return (
    <Notice tone="warning" title={`Verify every required document before ${action}`}>
      {labels.length <= 3 ? `Outstanding: ${labels.join(", ")}.` : `${labels.length} documents are still outstanding — see Documents.`}
    </Notice>
  );
}

function StageActionCard({
  application,
  state,
  onChanged,
  nextHref,
}: {
  application: ApplicationDetail;
  state?: ApplicationWorkflowState;
  onChanged: () => void;
  nextHref?: string;
}) {
  const { staff, can } = useStaffAuth();
  const [note, setNote] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [decidedStageId, setDecidedStageId] = useState<string | null>(null);
  const action = useAction();
  const stage = state?.current_stage;

  if (done && application.status !== "under_review") {
    return (
      <Card className="border-success/30">
        <Notice tone="success" title={done} />
        {nextHref && (
          <ButtonLink href={nextHref} className="mt-4 w-full">
            Next application <ArrowRight className="h-4 w-4" />
          </ButtonLink>
        )}
      </Card>
    );
  }
  if (!stage || application.status !== "under_review") return null;

  const holdsStageRole = !!staff && (staff.is_super_admin || staff.role?.id === stage.approver_role_id);
  const canAct = can(P.LOAN_REVIEW) && holdsStageRole;
  const isFinalStage = !!state && !state.pipeline_stages.some((s) => s.status === "upcoming");
  const outstanding = isFinalStage ? unverifiedDocuments(application) : [];

  async function decide(decision: "approved" | "rejected") {
    if (decision === "rejected" && !note.trim()) {
      action.setError("Add a note explaining the rejection.");
      return;
    }
    const ok = await action.run(() => applicationsApi.stageAction(application.id, decision, note.trim() || undefined));
    if (ok) {
      setNote("");
      setDone(decision === "rejected" ? "Application rejected" : isFinalStage ? "Final approval recorded" : `${stage!.name} approved`);
      setDecidedStageId(stage!.id);
      onChanged();
    }
  }

  return (
    <Card className="border-cyan/30 ring-1 ring-cyan/10">
      {done && decidedStageId !== stage.id && (
        <Notice tone="success" className="mb-4" title={done}>
          Now at {stage.name}.
        </Notice>
      )}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-wider text-cyan">Your decision</p>
          <h3 className="mt-1 text-[15px] font-semibold text-ink">{stage.name}</h3>
          <p className="mt-0.5 text-xs text-ink-3">
            Waiting on {stage.approver_role_name ?? "an approver"}
            {state?.current_stage_entered_at ? ` · ${relativeTime(state.current_stage_entered_at)}` : ""}
          </p>
        </div>
        {isFinalStage && <Badge variant="navy">Final stage</Badge>}
      </div>
      {canAct ? (
        <div className="space-y-3">
          <Field label="Note" hint="Required to reject. Recorded in the audit trail.">
            {(id, describedBy) => (
              <textarea
                id={id}
                aria-describedby={describedBy}
                className="input min-h-[76px] resize-y"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            )}
          </Field>
          <OutstandingDocuments labels={outstanding} action="final approval" />
          <InlineError message={action.error} />
          <div className="grid grid-cols-2 gap-2">
            <Button variant="danger-outline" disabled={action.busy} onClick={() => decide("rejected")}>
              <X className="h-4 w-4" /> Reject
            </Button>
            <Button variant="success" loading={action.busy} disabled={outstanding.length > 0} onClick={() => decide("approved")}>
              {!action.busy && <Check className="h-4 w-4" />} {isFinalStage ? "Give final approval" : "Approve stage"}
            </Button>
          </div>
        </div>
      ) : (
        <Notice tone="info">
          Only staff with the <strong>{stage.approver_role_name}</strong> role can act on this stage.
        </Notice>
      )}
    </Card>
  );
}

// ── Terms (approved amount, tenure, cadence) and manual rejection ────────

function OfferSchedulePreview({
  applicationId,
  amount,
  tenure,
  cadence,
}: {
  applicationId: string;
  amount: string;
  tenure: string;
  cadence: string;
}) {
  const [draft, setDraft] = useState({ amount, tenure, cadence });
  useEffect(() => {
    const timer = setTimeout(() => setDraft({ amount, tenure, cadence }), 400);
    return () => clearTimeout(timer);
  }, [amount, tenure, cadence]);

  const params: { approved_amount?: string; tenure_months?: number; repayment_cadence?: string } = {};
  if (draft.amount) params.approved_amount = String(draft.amount);
  if (draft.tenure) params.tenure_months = Number(draft.tenure);
  if (draft.cadence) params.repayment_cadence = draft.cadence;

  const preview = useResource(
    () => applicationsApi.offerPreview(applicationId, params),
    [applicationId, draft.amount, draft.tenure, draft.cadence],
  );

  if (preview.loading && !preview.data) {
    return (
      <div className="mt-4 border-t border-line pt-4">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="mt-3 h-24" />
      </div>
    );
  }
  if (preview.error) {
    return (
      <Notice tone="info" className="mt-4 border-t border-line pt-4" title="Repayment preview">
        Set approved amount and tenure (months) to see the schedule the customer will get.
      </Notice>
    );
  }
  if (!preview.data) return null;
  const o = preview.data;
  const shown = o.schedule.slice(0, 8);
  return (
    <div className="mt-4 border-t border-line pt-4">
      <h4 className="text-2xs font-semibold uppercase tracking-wider text-ink-3">Customer repayment preview</h4>
      <p className="mt-1 text-xs text-ink-3">
        Estimated from today; final due dates are set on disbursement. After payout, customers get push reminders{" "}
        <strong>3 days before</strong>, <strong>on the due date</strong>, and if overdue (daily job ~08:00 Lagos).
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-ink-3">Total to repay</dt>
          <dd className="num font-semibold text-ink">{money(o.total_repayable)}</dd>
        </div>
        <div>
          <dt className="text-ink-3">
            {o.installments} payments
          </dt>
          <dd className="num font-semibold text-ink">{money(o.first_payment)} each (1st)</dd>
        </div>
      </dl>
      <ul className="mt-3 max-h-48 overflow-y-auto rounded-lg border border-line text-sm">
        {shown.map((line) => (
          <li key={line.installment} className="flex justify-between gap-2 border-b border-line/70 px-3 py-2 last:border-0">
            <span className="text-ink-3">
              {line.installment}. {date(line.due_date)}
            </span>
            <span className="num font-medium text-ink">{money(line.amount)}</span>
          </li>
        ))}
      </ul>
      {o.schedule.length > shown.length ? (
        <p className="mt-1 text-xs text-ink-3">+ {o.schedule.length - shown.length} more installments</p>
      ) : null}
    </div>
  );
}

function TermsCard({ application, onChanged }: { application: ApplicationDetail; onChanged: () => void }) {
  const { can } = useStaffAuth();
  const [amount, setAmount] = useState(application.approved_amount ?? application.requested_amount ?? "");
  const [tenure, setTenure] = useState(String(application.tenure_months ?? ""));
  const [cadence, setCadence] = useState(application.repayment_cadence ?? "");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);
  const save = useAction();
  const reject = useAction();

  if (!TERMS_EDITABLE.includes(application.status) || !can(P.LOAN_REVIEW)) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaved(false);
    const body: { approved_amount?: string; tenure_months?: number; repayment_cadence?: string } = {};
    if (amount) body.approved_amount = String(amount);
    if (tenure) body.tenure_months = Number(tenure);
    if (cadence) body.repayment_cadence = cadence;
    if (await save.run(() => applicationsApi.updateTerms(application.id, body))) {
      setSaved(true);
      onChanged();
    }
  }

  async function confirmReject() {
    if (!reason.trim()) {
      reject.setError("A reason is required.");
      return;
    }
    if (await reject.run(() => applicationsApi.reject(application.id, reason.trim()))) {
      setRejectOpen(false);
      onChanged();
    }
  }

  return (
    <Card>
      <CardHeader
        title="Loan terms"
        description="Confirm amount and tenure before credit approval / customer offer. Schedule and totals update automatically."
      />
      <form onSubmit={submit} className="space-y-3">
        <Field label="Approved amount (₦)">
          {(id) => (
            <input id={id} className="input num" type="number" inputMode="decimal" min="1" step="0.01" value={amount} onChange={(e) => { setAmount(e.target.value); setSaved(false); }} />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tenure (months)">
            {(id) => (
              <input id={id} className="input num" type="number" inputMode="numeric" min="1" max="60" value={tenure} onChange={(e) => { setTenure(e.target.value); setSaved(false); }} />
            )}
          </Field>
          <Field label="Repayment">
            {(id) => (
              <select id={id} className="input" value={cadence} onChange={(e) => { setCadence(e.target.value); setSaved(false); }}>
                <option value="">Product default</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="salary_date">Salary date</option>
              </select>
            )}
          </Field>
        </div>
        <InlineError message={save.error} />
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <Button type="button" size="sm" variant="ghost" className="text-error hover:bg-error-soft hover:text-error" onClick={() => setRejectOpen(true)}>
            Reject application
          </Button>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-xs font-medium text-success" role="status">
                <Check className="h-3.5 w-3.5" /> Saved
              </span>
            )}
            <Button type="submit" size="sm" loading={save.busy}>
              Save terms
            </Button>
          </div>
        </div>
      </form>

      <OfferSchedulePreview applicationId={application.id} amount={String(amount)} tenure={tenure} cadence={cadence} />

      <Modal
        isOpen={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject application"
        description="This closes the application. The customer will see the reason."
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={reject.busy} onClick={confirmReject}>
              Reject application
            </Button>
          </>
        }
      >
        <Field label="Reason" required>
          {(id) => <textarea id={id} className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <div className="mt-3">
          <InlineError message={reject.error} />
        </div>
      </Modal>
    </Card>
  );
}

// ── Disbursement ──────────────────────────────────────────────────────────

function DisbursementCard({ application, onChanged }: { application: ApplicationDetail; onChanged: () => void }) {
  const { can } = useStaffAuth();
  const [manualOpen, setManualOpen] = useState(false);
  const [reference, setReference] = useState("");
  const [disbursedOn, setDisbursedOn] = useState(todayIso());
  const [note, setNote] = useState("");
  const rail = useAction();
  const manual = useAction();
  const loanLookup = useResource(
    () =>
      application.status === "disbursed"
        ? loansApi.list({ customer_id: application.customer_id, limit: 100 })
        : Promise.resolve(null),
    [application.status, application.customer_id],
  );

  if (application.status === "ready_to_disburse") {
    return (
      <Card>
        <Notice tone="info" title="Disbursement in progress">
          The transfer was sent to the bank and is awaiting confirmation. It completes on the bank&apos;s callback or the
          next reconciliation run — do not pay this customer again manually.
        </Notice>
      </Card>
    );
  }

  if (application.status === "disbursed") {
    const loan = loanLookup.data?.items.find((l) => l.application_id === application.id);
    return (
      <Card>
        <Notice tone="success" title="Disbursed">
          The loan is on the book with its repayment schedule.
        </Notice>
        {loan && (
          <ButtonLink href={`/admin/loans/${loan.id}`} variant="outline" className="mt-4 w-full">
            Open loan & schedule <ArrowRight className="h-4 w-4" />
          </ButtonLink>
        )}
      </Card>
    );
  }

  if (application.status !== "approved" || !can(P.LOAN_DISBURSE)) return null;

  const outstanding = unverifiedDocuments(application);
  const amount = application.approved_amount ?? application.requested_amount;
  const termsSet = !!application.tenure_months && !!amount;
  const ready = termsSet && outstanding.length === 0;
  const uf = application.universal_form;

  async function sendViaRail() {
    if (await rail.run(() => applicationsApi.disburse(application.id, "Disbursed from staff portal"))) onChanged();
  }

  async function recordManual() {
    if (reference.trim().length < 4) {
      manual.setError("Enter the bank transfer reference (at least 4 characters).");
      return;
    }
    const ok = await manual.run(() =>
      applicationsApi.recordManualDisbursement(application.id, {
        external_reference: reference.trim(),
        disbursed_on: disbursedOn,
        note: note.trim() || undefined,
      }),
    );
    if (ok) {
      setManualOpen(false);
      onChanged();
    }
  }

  return (
    <Card className="border-success/30 ring-1 ring-success/10">
      <p className="text-2xs font-semibold uppercase tracking-wider text-success">Ready to pay out</p>
      <p className="num mt-1 text-2xl font-semibold tracking-tight text-ink">{money(amount)}</p>
      <dl className="mt-3 space-y-1.5 rounded-lg bg-gray-50 px-3 py-2.5 text-[13px]">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-3">Account name</dt>
          <dd className="truncate font-medium text-ink">{String(uf.bank_account_name ?? "—")}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-3">Bank</dt>
          <dd className="truncate font-medium text-ink">{String(uf.bank_name ?? "—")}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-3">Account number</dt>
          <dd className="num font-mono font-medium text-ink">{String(uf.bank_account_number ?? "—")}</dd>
        </div>
      </dl>
      <div className="mt-3 space-y-2">
        {!termsSet && <Notice tone="warning">Set the approved amount and tenure in Loan terms first.</Notice>}
        <OutstandingDocuments labels={outstanding} action="disbursing" />
        <InlineError message={rail.error} />
      </div>
      <div className="mt-4 grid gap-2">
        <Button variant="success" loading={rail.busy} disabled={!ready} onClick={sendViaRail}>
          {!rail.busy && <Send className="h-4 w-4" />} Send via payment rail
        </Button>
        <Button variant="outline" disabled={!ready} onClick={() => setManualOpen(true)}>
          <Banknote className="h-4 w-4" /> Record manual disbursement
        </Button>
      </div>

      <Modal
        isOpen={manualOpen}
        onClose={() => setManualOpen(false)}
        title="Record manual disbursement"
        description="Only for money already sent outside the system (bank app or branch). The loan is booked with its repayment schedule immediately."
        footer={
          <>
            <Button variant="outline" onClick={() => setManualOpen(false)}>
              Cancel
            </Button>
            <Button loading={manual.busy} onClick={recordManual}>
              Record & book loan
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Bank transfer reference" required hint="e.g. NIP session ID">
            {(id, d) => <input id={id} aria-describedby={d} className="input font-mono" value={reference} onChange={(e) => setReference(e.target.value)} />}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date sent">
              {(id) => <input id={id} className="input" type="date" max={todayIso()} value={disbursedOn} onChange={(e) => setDisbursedOn(e.target.value)} />}
            </Field>
            <Field label="Note (optional)">
              {(id) => <input id={id} className="input" value={note} onChange={(e) => setNote(e.target.value)} />}
            </Field>
          </div>
          <InlineError message={manual.error} />
        </div>
      </Modal>
    </Card>
  );
}

// ── Documents ─────────────────────────────────────────────────────────────

function DocumentsCard({ application, onChanged }: { application: ApplicationDetail; onChanged: () => void }) {
  const { can } = useStaffAuth();
  const action = useAction();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<DocumentChecklistItem | null>(null);
  const [note, setNote] = useState("");
  const canVerify = can(P.LOAN_VERIFY_DOCS) && application.status !== "draft";

  const doc = (item: DocumentChecklistItem) => application.documents.find((d) => d.id === item.document_id);
  const required = application.document_checklist.filter((d) => d.required);
  const verifiedCount = required.filter((d) => d.status === "verified").length;
  const pct = required.length ? Math.round((verifiedCount / required.length) * 100) : 0;

  async function verify(item: DocumentChecklistItem, status: "verified" | "rejected", rejectionNote?: string) {
    if (!item.document_id) return;
    setBusyId(item.document_id);
    const ok = await action.run(() => applicationsApi.verifyDocument(application.id, item.document_id!, status, rejectionNote));
    setBusyId(null);
    if (ok) {
      setRejecting(null);
      setNote("");
      onChanged();
    }
  }

  return (
    <Card flush>
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[15px] font-semibold text-ink">Documents</h3>
            <p className="mt-0.5 text-xs text-ink-3">
              <span className="num font-medium text-ink-2">{verifiedCount} of {required.length}</span> required documents verified
            </p>
          </div>
          <div className="flex w-40 items-center gap-2" aria-hidden>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-100">
              <div className={cn("h-full rounded-full", pct === 100 ? "bg-success" : "bg-navy")} style={{ width: `${pct}%` }} />
            </div>
            <span className="num w-9 text-right text-xs font-semibold text-ink-2">{pct}%</span>
          </div>
        </div>
        {action.error && <div className="mt-3"><InlineError message={action.error} /></div>}
      </div>
      <ul className="divide-y divide-line">
        {application.document_checklist.map((item) => {
          const file = doc(item);
          const busy = busyId === item.document_id;
          return (
            <li key={item.document_type} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3 transition-colors hover:bg-gray-50/70">
              <span
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                  item.status === "verified" ? "bg-success-soft text-success" : item.status === "rejected" ? "bg-error-soft text-error" : "bg-gray-100 text-ink-3",
                )}
                aria-hidden
              >
                {item.status === "verified" ? <CheckCircle2 className="h-4 w-4" /> : item.status === "rejected" ? <XCircle className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink">
                  {item.label}
                  {item.required && <span className="text-error" aria-label="required"> *</span>}
                </p>
                <p className="truncate text-xs text-ink-3">
                  {file ? `${file.file_name} · ${Math.max(1, Math.round(file.size_bytes / 1024))} KB` : "Not uploaded"}
                  {file?.rejection_note ? <span className="text-error"> · Rejected: {file.rejection_note}</span> : null}
                </p>
              </div>
              {item.status && <StatusBadge status={item.status} />}
              {file && (
                <div className="flex items-center gap-1.5">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Download ${item.label}`}
                    title="Download"
                    onClick={() => action.run(() => applicationsApi.downloadDocument(application.id, file.id, file.file_name))}
                  >
                    <Download className="h-4 w-4" />
                  </Button>
                  {canVerify && item.status !== "rejected" && (
                    <Button size="xs" variant="outline" disabled={action.busy} onClick={() => setRejecting(item)} aria-label={`Reject ${item.label}`}>
                      Reject
                    </Button>
                  )}
                  {canVerify && item.status !== "verified" && (
                    <Button size="xs" variant="success" loading={busy} disabled={action.busy && !busy} onClick={() => verify(item, "verified")} aria-label={`Verify ${item.label}`}>
                      {!busy && <Check className="h-3.5 w-3.5" />} Verify
                    </Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <Modal
        isOpen={!!rejecting}
        onClose={() => setRejecting(null)}
        title={`Reject ${rejecting?.label ?? "document"}`}
        description="The customer is asked to upload it again."
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setRejecting(null)}>
              Cancel
            </Button>
            <Button variant="danger" disabled={!note.trim()} loading={action.busy} onClick={() => rejecting && verify(rejecting, "rejected", note.trim())}>
              Reject document
            </Button>
          </>
        }
      >
        <Field label="What's wrong with this document?" required>
          {(id) => <textarea id={id} className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </Modal>
    </Card>
  );
}

// ── Applicant details ─────────────────────────────────────────────────────

const SECTIONS: { title: string; fields: [string, string][] }[] = [
  {
    title: "Contact",
    fields: [
      ["phone", "Phone"],
      ["email", "Email"],
      ["residential_address", "Address"],
    ],
  },
  {
    title: "Loan request",
    fields: [
      ["monthly_income", "Monthly income"],
      ["purpose", "Purpose"],
      ["repayment_period", "Repayment period (as entered)"],
      ["source_of_repayment", "Source of repayment"],
    ],
  },
  {
    title: "Payout account",
    fields: [
      ["bank_name", "Bank"],
      ["bank_code", "Bank code"],
      ["bank_account_number", "Account number"],
      ["bank_account_name", "Account name"],
    ],
  },
  {
    title: "Next of kin",
    fields: [
      ["next_of_kin_name", "Name"],
      ["next_of_kin_phone", "Phone"],
      ["next_of_kin_relationship", "Relationship"],
    ],
  },
];

function ApplicantCard({ application }: { application: ApplicationDetail }) {
  const form = application.universal_form as Record<string, unknown>;
  const productData = Object.entries(application.product_data ?? {});
  const show = (key: string, value: unknown) =>
    value === null || value === undefined || value === "" ? null : key === "monthly_income" ? money(value as string) : String(value);

  return (
    <Card>
      <CardHeader title="Application details" />
      <div className="space-y-6">
        {SECTIONS.map((s) => (
          <section key={s.title}>
            <h4 className="mb-3 text-2xs font-semibold uppercase tracking-wider text-ink-3">{s.title}</h4>
            <DescriptionList
              columns={3}
              items={s.fields.map(([key, label]) => ({
                label,
                value: show(key, form[key]),
                mono: key === "bank_account_number" || key === "bank_code",
              }))}
            />
          </section>
        ))}
        {productData.length > 0 && (
          <section>
            <h4 className="mb-3 text-2xs font-semibold uppercase tracking-wider text-ink-3">{application.product_name} details</h4>
            <DescriptionList columns={3} items={productData.map(([key, value]) => ({ label: humanize(key), value: value === null ? null : String(value) }))} />
          </section>
        )}

        {application.guarantors.length > 0 && (
          <section>
            <h4 className="mb-3 text-2xs font-semibold uppercase tracking-wider text-ink-3">Guarantors</h4>
            <ul className="grid gap-2 sm:grid-cols-2">
              {application.guarantors.map((g) => (
                <li key={g.id} className="rounded-lg border border-line px-4 py-3 text-sm">
                  <p className="font-medium text-ink">{g.full_name}</p>
                  <p className="text-xs text-ink-3">
                    {[g.relationship, g.phone, g.id_type && `${g.id_type} ${g.id_number ?? ""}`].filter(Boolean).join(" · ") || "—"}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {application.collaterals.length > 0 && (
          <section>
            <h4 className="mb-3 text-2xs font-semibold uppercase tracking-wider text-ink-3">Collateral</h4>
            <ul className="grid gap-2 sm:grid-cols-2">
              {application.collaterals.map((c) => (
                <li key={c.id} className="rounded-lg border border-line px-4 py-3 text-sm">
                  <p className="font-medium text-ink">
                    {humanize(c.collateral_type)} · <span className="num">{money(c.estimated_value)}</span>
                  </p>
                  <p className="text-xs text-ink-3">
                    {c.description} · {humanize(c.custody_status)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Card>
  );
}

// ── Audit trail ───────────────────────────────────────────────────────────

function AuditCard({
  entries,
  error,
}: {
  entries?: { id: string; event_type: string; actor_label: string | null; actor_type: string; message: string | null; created_at: string }[];
  error: string | null;
}) {
  const [all, setAll] = useState(false);
  if (error) return <ErrorState message={error} />;
  const shown = all ? entries ?? [] : (entries ?? []).slice(0, 8);
  return (
    <Card>
      <CardHeader
        title="Audit trail"
        description="Every view, decision and change on this application"
        actions={
          <Link href="/admin/audit" className="link inline-flex items-center gap-1 text-[13px]">
            Full audit log <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        }
      />
      {!entries || entries.length === 0 ? (
        <Empty title="No events yet" compact />
      ) : (
        <>
          <ol className="space-y-0">
            {shown.map((e) => (
              <li key={e.id} className="flex gap-3 border-b border-line/70 py-2.5 last:border-0">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gray-300" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{e.message ?? humanize(e.event_type)}</p>
                  <p className="text-xs text-ink-3">{e.actor_label ?? humanize(e.actor_type)}</p>
                </div>
                <time className="shrink-0 text-xs text-ink-3" dateTime={e.created_at} title={dateTime(e.created_at)}>
                  {relativeTime(e.created_at)}
                </time>
              </li>
            ))}
          </ol>
          {entries.length > 8 && (
            <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAll((v) => !v)}>
              {all ? "Show fewer" : `Show all ${entries.length} events`}
            </Button>
          )}
        </>
      )}
    </Card>
  );
}
