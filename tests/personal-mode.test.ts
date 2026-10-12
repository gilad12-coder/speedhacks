import { afterEach, expect, it, vi } from "vitest";
import { personalMode } from "@/lib/personal-mode";
afterEach(() => vi.unstubAllEnvs());
it("only permits same-origin loopback requests in explicitly enabled development", () => {
  vi.stubEnv("NODE_ENV", "development"); vi.stubEnv("PERSONAL_MODE", "1");
  vi.stubEnv("APP_URL", "http://127.0.0.1:3000");
  expect(personalMode("127.0.0.1:3000", "http://127.0.0.1:3000")).toBe(true);
  expect(personalMode("127.0.0.1:3000", "https://evil.example")).toBe(false);
  expect(personalMode("127.0.0.1:3000", null)).toBe(false);
  expect(personalMode("evil.example", "http://127.0.0.1:3000")).toBe(false);
  vi.stubEnv("NODE_ENV", "production");
  expect(personalMode("127.0.0.1:3000", "http://127.0.0.1:3000")).toBe(false);
  vi.stubEnv("NODE_ENV", "development"); vi.stubEnv("APP_URL", "https://public.example");
  expect(personalMode("public.example", "https://public.example")).toBe(false);
});
