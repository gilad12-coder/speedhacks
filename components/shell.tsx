import Link from "next/link";
import { KeyRound } from "lucide-react";

export function Wordmark({ tone = "ink", size = "md" }: { tone?: "ink" | "light"; size?: "md" | "lg" | "xl" }) {
  return (
    <Link
      href="/"
      className={`inline-flex items-center font-display font-semibold tracking-tight ${
        size === "xl" ? "gap-4 text-7xl" : size === "lg" ? "gap-3 text-4xl" : "gap-2 text-lg"
      } ${tone === "light" ? "text-on-green" : "text-green"}`}
    >
      {size !== "xl" && <KeyRound aria-hidden className={size === "lg" ? "size-9" : "size-5"} strokeWidth={2} />}
      Keyhunt
    </Link>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "quiet" }) {
  const styles = {
    primary: "bg-green text-on-green hover:bg-green-hover shadow-lift",
    secondary: "bg-surface text-ink border border-line-strong hover:border-ink-3",
    quiet: "text-green-ink hover:bg-green-soft",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}
