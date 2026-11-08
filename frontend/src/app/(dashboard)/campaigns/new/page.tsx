"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { SmsComposer } from "@/components/SmsComposer";
import { Alert, Button, Card, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { colomboLocalToIso, lkr, num } from "@/lib/format";
import type { Campaign, Estimate, Group, SenderId, Template, Wallet } from "@/types/api";

const STEPS = ["Audience", "Message", "Sender & schedule", "Review & confirm"] as const;
const BASE_VARS = ["first_name", "last_name", "name", "phone"];

export default function NewCampaignPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [allContacts, setAllContacts] = useState(false);
  const [numbers, setNumbers] = useState("");
  const [category, setCategory] = useState<"promotional" | "transactional">("promotional");
  const [body, setBody] = useState("");
  const [sender, setSender] = useState("");
  const [when, setWhen] = useState<"now" | "later">("now");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [fallback, setFallback] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);

  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/templates") });
  const senders = useQuery({ queryKey: ["sender-ids"], queryFn: () => api<SenderId[]>("/sender-ids") });
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: () => api<Wallet>("/billing/wallet") });
  const isDemo = wallet.data?.mode === "demo";
  const approved = senders.data?.filter((s) => s.status === "approved") ?? [];

  const numberList = useMemo(() => numbers.split(/[\s,;]+/).map((n) => n.trim()).filter(Boolean), [numbers]);
  const audienceOk = allContacts || groupIds.length > 0 || numberList.length > 0;

  function payload() {
    return {
      name: name || "Untitled campaign",
      body,
      category,
      sender: sender || null,
      audience: { group_ids: groupIds, numbers: numberList, all_contacts: allContacts },
      recurrence: recurrence || null,
      missing_variable_policy: fallback ? "fallback" : "skip",
      missing_variable_fallback: fallback,
    };
  }

  async function saveAndEstimate() {
    setBusy(true);
    setError(null);
    try {
      const c = campaign
        ? await api<Campaign>(`/campaigns/${campaign.id}`, { method: "PATCH", body: payload() })
        : await api<Campaign>("/campaigns", { method: "POST", body: payload() });
      setCampaign(c);
      setEstimate(await api<Estimate>(`/campaigns/${c.id}/estimate`, { method: "POST" }));
      setStep(3);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function launch() {
    if (!campaign) return;
    setBusy(true);
    setError(null);
    try {
      if (when === "later") {
        await api(`/campaigns/${campaign.id}/schedule`, { method: "POST", body: { scheduled_at: colomboLocalToIso(scheduledLocal) } });
      } else {
        await api(`/campaigns/${campaign.id}/send`, { method: "POST" });
      }
      router.push(`/campaigns/${campaign.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    setBusy(true);
    try {
      const c = campaign
        ? await api<Campaign>(`/campaigns/${campaign.id}`, { method: "PATCH", body: payload() })
        : await api<Campaign>("/campaigns", { method: "POST", body: payload() });
      router.push(`/campaigns/${c.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const canNext = [audienceOk && name.trim().length > 0, body.trim().length > 0, when === "now" || !!scheduledLocal, true][step];

  return (
    <>
      <PageHeader title="New campaign" description={isDemo ? "Demo mode: messages go through the demo gateway and use demo credits." : undefined} />
      <ol className="mb-6 flex flex-wrap gap-2 text-sm" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} className={`rounded-full px-3 py-1 ${i === step ? "bg-brand-600 text-white" : i < step ? "bg-brand-100 text-brand-800" : "bg-slate-100 text-slate-500"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      {error && <div className="mb-4"><Alert kind="error">{error}</Alert></div>}

      <Card>
        {step === 0 && (
          <div className="space-y-5">
            <Field label="Campaign name" htmlFor="cname"><Input id="cname" value={name} onChange={(e) => setName(e.target.value)} placeholder="Weekend sale" /></Field>
            <fieldset>
              <legend className="mb-2 text-sm font-medium text-slate-700">Groups</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={allContacts} onChange={(e) => setAllContacts(e.target.checked)} /> All contacts
                </label>
                {groups.data?.map((g) => (
                  <label key={g.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={groupIds.includes(g.id)}
                      onChange={(e) => setGroupIds((ids) => (e.target.checked ? [...ids, g.id] : ids.filter((x) => x !== g.id)))}
                    />
                    {g.name} <span className="text-slate-400">({num(g.member_count)})</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <Field label="Or paste numbers" htmlFor="nums" hint={`${numberList.length} numbers – one per line or comma separated. Duplicates are removed automatically.`}>
              <Textarea id="nums" rows={4} value={numbers} onChange={(e) => setNumbers(e.target.value)} placeholder={"0771234567\n0712345678"} />
            </Field>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Message type" htmlFor="cat" hint={category === "promotional" ? "Requires consent and an opt-out (e.g. 'Reply STOP to opt out'). Not sent 9pm–8am." : "Order, appointment and account updates."}>
                <Select id="cat" value={category} onChange={(e) => setCategory(e.target.value as typeof category)}>
                  <option value="promotional">Promotional</option>
                  <option value="transactional">Transactional</option>
                </Select>
              </Field>
              <Field label="Start from template" htmlFor="tpl">
                <Select id="tpl" defaultValue="" onChange={(e) => { const tp = templates.data?.find((x) => x.id === e.target.value); if (tp) setBody(tp.body); }}>
                  <option value="">—</option>
                  {templates.data?.map((tp) => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="Message" htmlFor="body">
              <SmsComposer id="body" value={body} onChange={setBody} variables={[...BASE_VARS, "city"]} rows={6} placeholder="Hi {{first_name}}, …" />
            </Field>
            {category === "promotional" && !/\b(stop|unsubscribe|opt[\s-]?out)\b/i.test(body) && body && (
              <Alert kind="warning">Add an opt-out instruction such as &ldquo;Reply STOP to opt out&rdquo;.</Alert>
            )}
            <Field label="If a variable is missing" htmlFor="fb" hint="Leave empty to skip contacts with missing values, or enter a fallback (e.g. 'Customer').">
              <Input id="fb" value={fallback} onChange={(e) => setFallback(e.target.value)} />
            </Field>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <Field label="Sender ID" htmlFor="sender" hint={isDemo ? "Demo messages use 'SMSFlow' unless you set one." : "Only approved sender IDs can be used. Request one in Settings."}>
              {isDemo ? (
                <Input id="sender" maxLength={11} value={sender} onChange={(e) => setSender(e.target.value)} placeholder="SMSFlow" />
              ) : (
                <Select id="sender" value={sender} onChange={(e) => setSender(e.target.value)}>
                  <option value="">Select…</option>
                  {approved.map((s) => <option key={s.id}>{s.value}</option>)}
                </Select>
              )}
            </Field>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-slate-700">When</legend>
              <label className="flex items-center gap-2 text-sm"><input type="radio" checked={when === "now"} onChange={() => setWhen("now")} /> Send immediately</label>
              <label className="flex items-center gap-2 text-sm"><input type="radio" checked={when === "later"} onChange={() => setWhen("later")} /> Schedule (Asia/Colombo time)</label>
            </fieldset>
            {when === "later" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Date & time" htmlFor="at"><Input id="at" type="datetime-local" value={scheduledLocal} onChange={(e) => setScheduledLocal(e.target.value)} /></Field>
                <Field label="Repeat" htmlFor="rr">
                  <Select id="rr" value={recurrence} onChange={(e) => setRecurrence(e.target.value)}>
                    <option value="">Does not repeat</option>
                    <option value="FREQ=DAILY">Daily</option>
                    <option value="FREQ=WEEKLY">Weekly</option>
                    <option value="FREQ=MONTHLY">Monthly</option>
                  </Select>
                </Field>
              </div>
            )}
          </div>
        )}

        {step === 3 && estimate && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-4">
              <Summary label="Recipients" value={num(estimate.recipients)} />
              <Summary label="SMS segments" value={`${num(estimate.segments)} (${estimate.encoding})`} />
              <Summary label={estimate.is_demo ? "Demo credits needed" : "Estimated cost"} value={estimate.is_demo ? num(estimate.segments) : lkr(estimate.cost)} />
              <Summary label={estimate.is_demo ? "Demo credits left" : "Available balance"} value={estimate.is_demo ? num(estimate.demo_credits) : lkr(estimate.available_balance)} />
            </div>
            {Object.values(estimate.skipped).some((v) => v > 0) && (
              <Alert kind="info">
                Skipped: {Object.entries(estimate.skipped).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ")}
              </Alert>
            )}
            {!estimate.sufficient && <Alert kind="error">Not enough {estimate.is_demo ? "demo credits" : "balance"} to send this campaign. Top up in Billing.</Alert>}
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700">Preview</p>
              <div className="space-y-2">
                {estimate.sample.map((s) => (
                  <div key={s.to} className="rounded-lg bg-slate-50 p-3 text-sm">
                    <p className="font-mono text-xs text-slate-500">{s.to} · {s.segments} segment(s)</p>
                    <p className="mt-1 whitespace-pre-wrap text-slate-800">{s.body}</p>
                  </div>
                ))}
              </div>
            </div>
            <p className="text-sm text-slate-500">
              {when === "later" ? `Scheduled for ${scheduledLocal.replace("T", " ")} (Asia/Colombo)${recurrence ? `, repeating ${recurrence.split("=")[1].toLowerCase()}` : ""}.` : "Sends immediately."}{" "}
              Funds are reserved now; unused amounts are released when the campaign completes.
            </p>
          </div>
        )}

        <div className="mt-8 flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-4">
          <Button variant="secondary" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>Back</Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={saveDraft} disabled={busy || !name}>Save draft</Button>
            {step < 2 && <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Next</Button>}
            {step === 2 && <Button onClick={saveAndEstimate} loading={busy} disabled={!canNext}>Review cost</Button>}
            {step === 3 && (
              <Button onClick={launch} loading={busy} disabled={!estimate?.sufficient || !estimate?.recipients}>
                {when === "later" ? "Schedule campaign" : "Send now"}
              </Button>
            )}
          </div>
        </div>
      </Card>
    </>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-900">{value}</p>
    </div>
  );
}
