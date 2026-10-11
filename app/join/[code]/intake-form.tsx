"use client";

import { ArrowLeft, ArrowRight, MapPin, Route, TrainFront, UserRound, Wallet, type LucideIcon } from "lucide-react";
import { startTransition, useActionState, useEffect, useRef, useState } from "react";
import { submitIntake, type FormState } from "@/app/actions";
import { DateField, todayIso } from "@/components/date-field";
import { NumberStepper } from "@/components/number-stepper";
import { AddressField } from "@/components/address-field";
import { CommuteModes } from "@/components/commute-modes";
import { Button } from "@/components/shell";
import type { Housemate } from "@/lib/types";

const inputClass =
  "h-12 w-full rounded-xl border border-line bg-surface px-4 text-lg text-ink placeholder:text-ink-3 hover:border-line-strong aria-[invalid=true]:border-red-ink";

interface Step {
  key: string;
  title: string;
  icon: LucideIcon;
  hint?: string;
  fields: string[]; // server field names, to jump back to the step that failed
  body: (err: Record<string, string>) => React.ReactNode;
}

function Field({
  label,
  hint,
  htmlFor,
  error,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  error?: string;
  children: React.ReactNode;
}) {
  const Label = htmlFor ? "label" : "p";
  return (
    <div>
      <Label htmlFor={htmlFor} className="block text-sm font-medium text-ink-2">
        {label}
      </Label>
      {hint && <p className="mt-0.5 text-sm text-ink-3">{hint}</p>}
      <div className="mt-2">{children}</div>
      {error && <p className="mt-2 text-sm text-red-ink">{error}</p>}
    </div>
  );
}

export function IntakeForm({
  code,
  me,
  names,
  solo,
  searchStarted,
  header,
  aside,
  children,
}: {
  code: string;
  me: Housemate | null;
  names: { firstName: string; lastName: string };
  solo: boolean;
  searchStarted: boolean;
  header: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [state, action, pending] = useActionState<FormState, FormData>(
    submitIntake.bind(null, code),
    {},
  );
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  // The step being animated out; it stays rendered until its exit ends.
  const [leaving, setLeaving] = useState<number | null>(null);
  const [moveInFrom, setMoveInFrom] = useState(me?.moveInFrom ?? "");
  // Checked on "Next" in the browser, so mistakes show inline instead of in the browser's own bubbles.
  const [clientErr, setClientErr] = useState<Record<string, string>>({});
  // The server's errors are copied here so fixing a field clears its error, like a browser-side one.
  const [serverErr, setServerErr] = useState<Record<string, string>>({});
  useEffect(() => setServerErr(state.fieldErrors ?? {}), [state]);
  const without = (name: string) => (errors: Record<string, string>) => {
    if (!(name in errors)) return errors;
    const rest = { ...errors };
    delete rest[name];
    return rest;
  };
  const clearError = (name: string) => {
    setClientErr(without(name));
    setServerErr(without(name));
  };
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);
  const firstRender = useRef(true);

  const steps: Step[] = [
    {
      key: "you",
      icon: UserRound,
      title: "First, a little about you",
      hint: "The name Keyhunt gives landlords.",
      fields: ["firstName"],
      body: (err) => (
        <div className="grid gap-6">
          <div className="grid grid-cols-2 gap-4">
            <Field label="First name" htmlFor="q-name" error={err.firstName}>
              <input
                id="q-name"
                name="firstName"
                data-field="firstName"
                data-required="Add your first name"
                defaultValue={names.firstName}
                autoComplete="given-name"
                maxLength={40}
                aria-invalid={!!err.firstName}
                className={inputClass}
              />
            </Field>
          </div>
        </div>
      ),
    },
    {
      key: "where",
      icon: MapPin,
      title: "Where you want to live",
      hint: "A city or any address.",
      fields: ["location"],
      body: (err) => (
        <Field label="City, neighborhood or address" htmlFor="q-location" error={err.location}>
          <AddressField
            id="q-location"
            name="location"
            kind="area"
            data-field="location"
            data-required="Where do you want to live?"
            defaultValue={me?.location}
            placeholder="Search a US city, neighborhood or address"
            maxLength={120}
            aria-invalid={!!err.location}
            className={inputClass}
          />
        </Field>
      ),
    },
    {
      key: "rent",
      icon: Wallet,
      title: "Rent and move-in",
      fields: ["maxBudgetUsd", "moveInFrom", "moveInTo"],
      body: (err) => (
        <div className="grid gap-6">
          <div className="grid grid-cols-2 gap-4">
            <Field label={solo ? "Most you'd pay per month" : "Most you'd pay, your share per month"} htmlFor="q-budget" error={err.maxBudgetUsd}>
              <NumberStepper
                id="q-budget"
                name="maxBudgetUsd"
                label="Rent"
                prefix="$"
                min={300}
                max={20000}
                step={50}
                defaultValue={me?.maxBudgetUsd ?? 1500}
                invalid={!!err.maxBudgetUsd}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Earliest move-in" htmlFor="q-from" error={err.moveInFrom}>
              <DateField
                id="q-from"
                name="moveInFrom"
                defaultValue={me?.moveInFrom}
                min={todayIso()}
                requiredMessage="Pick your earliest move-in"
                invalid={!!err.moveInFrom}
                onChange={(iso) => {
                  setMoveInFrom(iso);
                  clearError("moveInFrom");
                }}
              />
            </Field>
            <Field label="Latest move-in" htmlFor="q-to" error={err.moveInTo}>
              <DateField
                id="q-to"
                name="moveInTo"
                defaultValue={me?.moveInTo}
                min={moveInFrom || todayIso()}
                requiredMessage="Pick your latest move-in"
                invalid={!!err.moveInTo}
                onChange={() => clearError("moveInTo")}
              />
            </Field>
          </div>
        </div>
      ),
    },
    {
      key: "commute",
      icon: Route,
      title: "Your commute",
      fields: ["commuteDestination", "maxCommuteMinutes"],
      body: (err) => (
        <div className="grid gap-6">
          <Field label="Where you commute to" htmlFor="q-destination" error={err.commuteDestination}>
            <AddressField
              id="q-destination"
              name="commuteDestination"
              defaultValue={me?.commute.destination}
              placeholder="Search an address, office or campus"
              data-field="commuteDestination"
              data-required="Where do you commute to?"
              aria-invalid={!!err.commuteDestination}
              className={inputClass}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Longest trip, one way" htmlFor="q-minutes" error={err.maxCommuteMinutes}>
              <NumberStepper
                id="q-minutes"
                name="maxCommuteMinutes"
                label="Minutes"
                suffix="min"
                min={5}
                max={180}
                step={5}
                defaultValue={me?.commute.maxMinutes ?? 45}
                invalid={!!err.maxCommuteMinutes}
              />
            </Field>
          </div>
        </div>
      ),
    },
    {
      key: "modes",
      icon: TrainFront,
      title: "How you get there",
      hint: "Pick all that apply.",
      fields: ["commuteModes"],
      body: (err) => (
        <Field label="Ways you'd commute" error={err.commuteModes}>
          <CommuteModes
            defaultValue={me?.commute.modes.filter((m) => m !== "transit") ?? []}
            invalid={!!err.commuteModes}
          />
        </Field>
      ),
    },
  ];

  const last = steps.length - 1;
  const err = { ...serverErr, ...clientErr };

  const go = (next: number) => {
    const target = Math.max(0, Math.min(last, next));
    if (target === index) return;
    setDirection(target > index ? "forward" : "back");
    setLeaving(index);
    setIndex(target);
  };

  // Only the visible step is checked; hidden steps were checked when the user left them.
  const next = () => {
    const found: Record<string, string> = {};
    const required =
      stepRefs.current[index]?.querySelectorAll<HTMLInputElement>("input[data-required]") ?? [];
    for (const input of required) {
      if (!input.value.trim()) found[input.name] = input.dataset.required!;
    }
    const modes = stepRefs.current[index]?.querySelectorAll<HTMLInputElement>("input[name=commuteModes]");
    if (modes?.length && ![...modes].some((m) => m.checked)) found.commuteModes = "Pick at least one way you get there";
    const moveInTo = stepRefs.current[index]?.querySelector<HTMLInputElement>("input[name=moveInTo]")?.value;
    if (moveInFrom && moveInTo && moveInTo < moveInFrom) {
      found.moveInTo = "Latest move-in is before the earliest";
    }
    setClientErr(found);
    const first = Object.keys(found)[0];
    if (first) {
      stepRefs.current[index]?.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
      return;
    }
    go(index + 1);
  };

  useEffect(() => {
    const failed = steps.findIndex((s) => s.fields.some((f) => err[f]));
    if (failed >= 0) go(failed);
    // Jump only when a new server response arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const step = stepRefs.current[index];
    const target =
      step?.querySelector<HTMLElement>(
        "input:checked, [data-field], input:not([type=radio]):not([type=hidden])",
      ) ?? step?.querySelector("h2");
    target?.focus({ preventScroll: true });
  }, [index]);

  if (searchStarted) {
    return (
      <p className="mt-10 text-ink-2">
        The search has started, so preferences are locked.
      </p>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* The header holds the account menu's own sign-out form, so it must sit outside this one. */}
      <div className="px-12 pt-6 pb-5">{header}</div>
      <div
        role="progressbar"
        aria-label="Progress"
        aria-valuemin={1}
        aria-valuemax={steps.length}
        aria-valuenow={index + 1}
        className="h-1 bg-sunk"
      >
        <div
          className="h-full bg-green transition-[width] duration-700 ease-(--ease-out-expo)"
          style={{ width: `${((index + 1) / steps.length) * 100}%` }}
        />
      </div>
      {aside}
      <form
        // Submitted by hand rather than through `action`: React resets a form after its action
        // returns, which would wipe every typed answer whenever the server sends back an error.
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          startTransition(() => action(data));
        }}
        noValidate
        className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,7fr)]"
        onInput={(e) => clearError((e.target as HTMLInputElement).name)}
        onKeyDown={(e) => {
          if (
            e.key === "Enter" &&
            index < last &&
            (e.target as HTMLElement).tagName === "INPUT"
          ) {
            e.preventDefault();
            next();
          }
        }}
      >
          <div className="overflow-y-auto border-r border-line px-12 py-16">
            {children}
          </div>

          <div className="flex min-h-0 flex-col px-16 pt-16 pb-8">
            <div className="relative flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto">
              {steps.map((s, i) => (
                <div
                  key={s.key}
                  ref={(el) => {
                    stepRefs.current[i] = el;
                  }}
                  hidden={i !== index && i !== leaving}
                  aria-hidden={i === leaving || undefined}
                  inert={i === leaving}
                  onAnimationEnd={(e) => {
                    if (i === leaving && e.target === e.currentTarget)
                      setLeaving(null);
                  }}
                  className={`w-full max-w-2xl ${
                    i === index
                      ? `step-in step-in-${direction}`
                      : i === leaving
                        ? `step-out step-out-${direction}`
                        : ""
                  }`}
                >
                  <div className="flex items-center gap-4">
                    <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-green-soft text-green-ink">
                      <s.icon aria-hidden className="size-5" strokeWidth={1.75} />
                    </span>
                    <h2
                      tabIndex={-1}
                      className="font-display text-4xl leading-[1.05] font-semibold tracking-tight text-ink outline-none"
                    >
                      {s.title}
                    </h2>
                  </div>
                  {s.hint && (
                    <p className="mt-3 max-w-[60ch] text-lg text-ink-2">
                      {s.hint}
                    </p>
                  )}
                  <div className="mt-8">{s.body(err)}</div>
                </div>
              ))}
            </div>

            {state.error && (
              <p
                role="alert"
                className="mt-6 max-w-2xl rounded-xl bg-red-soft px-4 py-3 text-sm text-red-ink"
              >
                {state.error}
              </p>
            )}

            <div className="mt-8 flex max-w-2xl items-center justify-between gap-3 border-t border-line pt-6">
              <Button
                type="button"
                variant="secondary"
                aria-label="Back"
                onClick={() => go(index - 1)}
                disabled={index === 0 || pending}
                className={`w-10 px-0! ${index === 0 ? "invisible" : ""}`}
              >
                <ArrowLeft aria-hidden className="size-4 shrink-0" />
              </Button>
              {/* Distinct keys: if React reused the Next button as the submit button, the click
                  that reaches the last step would finish as a submit and send the form early. */}
              {index < last ? (
                <Button
                  key="next"
                  type="button"
                  aria-label="Next"
                  onClick={next}
                  className="w-10 px-0!"
                >
                  <ArrowRight aria-hidden className="size-4 shrink-0" />
                </Button>
              ) : (
                <Button key="submit" type="submit" disabled={pending}>
                  {pending ? "Saving…" : "Next: the interview"}
                </Button>
              )}
            </div>
          </div>
      </form>
    </div>
  );
}
