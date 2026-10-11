import { CircleAlert, ExternalLink, LoaderCircle, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { RentalResearch } from "@/lib/types";
import { usd } from "@/lib/view";

// Kinds the research worker reports. "Good" ones corroborate the listing; the rest are things to look into.
const FINDINGS: Record<string, { label: string; good: boolean }> = {
  address_corroborated: { label: "Address checks out", good: true },
  contact_corroborated: { label: "Contact checks out", good: true },
  rent_conflict: { label: "Rent differs between sources", good: false },
  contact_conflict: { label: "Contact differs between sources", good: false },
  upfront_payment: { label: "Asks for money up front", good: false },
  unavailable: { label: "May already be taken", good: false },
  price_outlier: { label: "Rent far below nearby places", good: false },
  other_concern: { label: "Something to look into", good: false },
};

function finding(kind: string) {
  return FINDINGS[kind] ?? { label: kind.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()), good: false };
}

const STATUS: Record<RentalResearch["status"], { label: string; tone: "green" | "amber" | "quiet" }> = {
  not_checked: { label: "Not screened yet", tone: "quiet" },
  checking: { label: "Checking sources", tone: "quiet" },
  unconfirmed: { label: "Couldn't confirm online", tone: "quiet" },
  cross_referenced: { label: "Checks out online", tone: "green" },
  concerns_found: { label: "Concerns to review", tone: "amber" },
  error: { label: "Screening incomplete", tone: "quiet" },
};

export function ScreeningBadge({ research }: { research: RentalResearch }) {
  const { label, tone } = STATUS[research.status];
  const Icon = research.status === "checking" ? LoaderCircle : tone === "green" ? ShieldCheck : tone === "amber" ? CircleAlert : ShieldQuestion;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        tone === "green" ? "bg-green-soft text-green-ink" : tone === "amber" ? "bg-amber-soft text-amber-ink" : "bg-sunk text-ink-2"
      }`}
    >
      <Icon aria-hidden className={`size-3.5 ${research.status === "checking" ? "animate-spin motion-reduce:animate-none" : ""}`} />
      {label}
    </span>
  );
}

// Where the asking rent sits against the median of nearby same-bedroom places.
export function RentVsMarket({ rent, research }: { rent: number | null; research: RentalResearch }) {
  const median = research.medianComparableRent;
  if (rent === null || median === null || median <= 0) return null;
  const diff = Math.round(((rent - median) / median) * 100);
  const suspicious = diff <= -25;
  const words = diff === 0 ? "right at" : diff < 0 ? `${-diff}% under` : `${diff}% over`;
  return (
    <span className={`text-xs ${suspicious ? "font-medium text-amber-ink" : "text-ink-2"}`}>
      {words} the {usd(median)} median of {research.comparableCount} nearby {research.comparableCount === 1 ? "place" : "places"}
    </span>
  );
}

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}

function Source({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs font-medium text-green-ink underline decoration-line-strong underline-offset-4 hover:text-green"
    >
      {host(url)}
      <ExternalLink aria-hidden className="size-3" />
    </a>
  );
}

export function ScreeningDetails({ research, rent }: { research: RentalResearch; rent: number | null }) {
  const concerns = research.findings.filter((f) => !finding(f.kind).good);
  const confirmations = research.findings.filter((f) => finding(f.kind).good);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <ScreeningBadge research={research} />
        <RentVsMarket rent={rent} research={research} />
      </div>

      {[...concerns, ...confirmations].length > 0 && (
        <ul className="mt-4 space-y-3">
          {[...concerns, ...confirmations].map((f, i) => {
            const { label, good } = finding(f.kind);
            return (
              <li key={i} className={`border-l-2 pl-3 ${good ? "border-green" : "border-amber-ink/60"}`}>
                <p className="text-sm font-medium text-ink">{label}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-ink-2">{f.summary}</p>
                {f.quote && <blockquote className="mt-1.5 font-display text-[0.9375rem] italic leading-snug text-ink">&ldquo;{f.quote}&rdquo;</blockquote>}
                <div className="mt-1">
                  <Source url={f.sourceUrl} />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {research.facts.length > 0 && (
        <dl className="mt-5 divide-y divide-line rounded-2xl border border-line">
          {research.facts.map((fact, i) => (
            <div key={i} className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3 px-4 py-2.5 text-sm">
              <dt className="font-medium capitalize text-ink-2">{fact.field.replaceAll("_", " ")}</dt>
              <dd className="min-w-0">
                <span className="text-ink">&ldquo;{fact.quote}&rdquo;</span> <Source url={fact.sourceUrl} />
              </dd>
            </div>
          ))}
        </dl>
      )}

      {research.medianComparableRent === null && research.status !== "checking" && research.status !== "not_checked" && (
        <p className="mt-4 text-xs text-ink-3">Not enough nearby places to tell whether the rent is unusually low.</p>
      )}
      {research.limitations && <p className="mt-3 text-xs leading-relaxed text-ink-3">{research.limitations}</p>}
    </div>
  );
}
