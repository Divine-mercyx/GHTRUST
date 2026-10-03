"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { DescriptionList, PageHeader } from "@/components/admin/Page";
import { Empty, ErrorState, PageSkeleton } from "@/components/admin/States";
import { settingsApi } from "@/lib/admin/endpoints";
import { useResource } from "@/lib/admin/hooks";
import { API_BASE } from "@/lib/admin/api";
import { SessionTimeoutCard } from "@/components/admin/SessionTimeoutCard";

export default function SettingsPage() {
  const settings = useResource(() => settingsApi.get());
  const branches = useResource(() => settingsApi.branches());

  if (settings.loading && !settings.data) return <PageSkeleton stats={false} />;
  if (settings.error) return <ErrorState message={settings.error} onRetry={settings.reload} />;
  const s = settings.data!;

  const checks: { label: string; ok: boolean; detail: string }[] = [
    {
      label: "BVN verification (Dojah)",
      ok: s.dojah_enabled && !s.dojah_mock,
      detail: s.dojah_enabled && !s.dojah_mock ? "Live" : "Mock mode — any BVN returns sample data",
    },
    { label: "SMS delivery", ok: !s.sms_mock, detail: s.sms_mock ? "Mock — codes are only written to the server log" : "Provider configured" },
    { label: "Rate limiting", ok: s.rate_limits_active, detail: s.rate_limits_active ? "Active" : "Off (development)" },
    { label: "Debug mode", ok: !s.debug, detail: s.debug ? "On — must be off in production" : "Off" },
  ];
  const attention = checks.filter((c) => !c.ok).length;

  return (
    <>
      <PageHeader
        title="Settings"
        description="The staff session timeout, and a read-only view of how the backend is configured."
        meta={<Badge variant={s.app_env === "production" ? "success" : "warning"} dot>{s.app_env}</Badge>}
      />

      <div className="grid items-start gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <SessionTimeoutCard />
          <Card>
            <CardHeader title="Environment" />
            <DescriptionList
              columns={3}
              items={[
                { label: "Environment", value: s.app_env },
                { label: "API", value: API_BASE, mono: true },
                { label: "Default branch", value: s.default_branch },
                { label: "OTP validity", value: `${Math.round(s.otp_expire_seconds / 60)} minutes` },
                { label: "Max document size", value: `${s.max_upload_size_mb} MB` },
              ]}
            />
          </Card>

          <Card flush>
            <div className="px-5 pt-5">
              <CardHeader
                title="Integrations"
                description={attention ? `${attention} item${attention === 1 ? "" : "s"} need attention before go-live` : "All integrations live"}
              />
            </div>
            <ul className="divide-y divide-line border-t border-line">
              {checks.map((c) => (
                <li key={c.label} className="flex items-center gap-3 px-5 py-3.5">
                  {c.ok ? <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden /> : <CircleAlert className="h-5 w-5 shrink-0 text-warning" aria-hidden />}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink">{c.label}</p>
                    <p className="text-xs text-ink-3">{c.detail}</p>
                  </div>
                  <Badge variant={c.ok ? "success" : "warning"}>{c.ok ? "OK" : "Attention"}</Badge>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <Card flush>
          <div className="px-5 pt-5">
            <CardHeader title="Branches" description="Derived from customer records" />
          </div>
          {(branches.data ?? []).length === 0 ? (
            <Empty title="No branches yet" compact />
          ) : (
            <ul className="divide-y divide-line border-t border-line">
              {(branches.data ?? []).map((b) => (
                <li key={b.name} className="flex justify-between px-5 py-3 text-sm">
                  <span className="font-medium text-ink">{b.name}</span>
                  <span className="num text-ink-3">
                    {b.customer_count} customer{b.customer_count === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
