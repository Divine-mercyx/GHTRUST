"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { securityApi, type SecuritySettings } from "@/lib/admin/endpoints";

const CHOICES = [5, 10, 15, 20, 30, 45, 60];

/**
 * Staff session timeout: the organisation's (a super admin edits it, others see it), and
 * a shorter one the signed-in staff member may choose for themselves.
 */
export function SessionTimeoutCard() {
  const [data, setData] = useState<SecuritySettings | null>(null);
  const [org, setOrg] = useState("");
  const [mine, setMine] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = (s: SecuritySettings) => {
    setData(s);
    setOrg(String(s.staff_idle_minutes));
    setMine(s.my_idle_minutes ? String(s.my_idle_minutes) : "");
  };

  useEffect(() => {
    securityApi
      .get()
      .then(apply)
      .catch((e: Error) => setNote({ ok: false, text: e.message }));
  }, []);

  const save = async (fn: () => Promise<SecuritySettings>, done: (s: SecuritySettings) => string) => {
    setBusy(true);
    setNote(null);
    try {
      const next = await fn();
      apply(next);
      setNote({ ok: true, text: done(next) });
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : "Could not save" });
    } finally {
      setBusy(false);
    }
  };

  const select = "input w-auto";

  return (
    <Card>
      <CardHeader
        title="Session timeout"
        description="Staff are signed out after this long without activity, with a minute's warning. Background refreshes don't count as activity."
      />
      {!data ? (
        <p className="text-sm text-ink-3">{note?.text ?? "Loading…"}</p>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-medium text-ink-2">
              Everyone
              <select className={`${select} mt-1 block`} value={org} disabled={!data.can_edit} onChange={(e) => setOrg(e.target.value)}>
                {CHOICES.map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </label>
            {data.can_edit ? (
              <Button
                loading={busy}
                disabled={org === String(data.staff_idle_minutes)}
                onClick={() =>
                  save(
                    () => securityApi.setOrg(Number(org)),
                    (s) => `Staff are now signed out after ${s.staff_idle_minutes} minutes without activity.`,
                  )
                }
              >
                Save
              </Button>
            ) : (
              <p className="text-xs text-ink-3">Only a super admin can change this.</p>
            )}
          </div>
          {data.updated_by_name ? (
            <p className="text-xs text-ink-3">
              Last changed by {data.updated_by_name}
              {data.updated_at ? ` on ${new Date(data.updated_at).toLocaleString()}` : ""}
            </p>
          ) : null}

          <div className="flex flex-wrap items-end gap-3 border-t border-line pt-4">
            <label className="text-xs font-medium text-ink-2">
              Just me (shorter only)
              <select className={`${select} mt-1 block`} value={mine} onChange={(e) => setMine(e.target.value)}>
                <option value="">Same as everyone ({data.staff_idle_minutes} minutes)</option>
                {CHOICES.filter((m) => m <= data.staff_idle_minutes).map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="outline"
              loading={busy}
              disabled={mine === (data.my_idle_minutes ? String(data.my_idle_minutes) : "")}
              onClick={() =>
                save(
                  () => securityApi.setMine(mine === "" ? null : Number(mine)),
                  (s) => `You'll be signed out after ${s.effective_idle_minutes} minutes without activity.`,
                )
              }
            >
              Save
            </Button>
          </div>
        </div>
      )}
      {data && note ? (
        <p role="status" className={`mt-4 text-sm ${note.ok ? "text-success" : "text-error"}`}>
          {note.text}
        </p>
      ) : null}
    </Card>
  );
}
