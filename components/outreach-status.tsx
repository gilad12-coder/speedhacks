import type { Outreach } from "@/lib/types";

export function OutreachStatus({ job }: { job?: Omit<Outreach, "listingId"> | null }) {
  if (!job || job.state === "complete") return null;
  const date = job.scheduledAt ? new Date(job.scheduledAt) : null;
  const when = date?.toLocaleString("en-US", { timeZone: job.timezone ?? "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  return <div className="my-3 rounded-xl bg-sunk px-4 py-3 text-sm">
    <p className="font-medium">{job.state === "scheduled" ? `Call scheduled · ${when}` : job.state === "calling" ? "Agent is calling" : job.state === "checking_hours" ? "Checking office hours" : job.state === "waiting_callback" ? "Waiting for a callback" : "Call needs attention"}</p>
    <p className="mt-1 text-ink-2">{job.reason}</p>
    {job.hoursQuote && <p className="mt-1 text-xs text-ink-2">{job.hoursSource === "assumed" ? "" : job.hoursSource?.startsWith("call:") ? "From the contact: " : "Published hours: "}{job.hoursQuote}</p>}
    {job.hoursSource?.startsWith("https://") && <a className="text-xs underline" href={job.hoursSource} target="_blank" rel="noopener noreferrer">Hours source</a>}
  </div>;
}
