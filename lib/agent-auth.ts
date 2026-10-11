import "server-only";
import { safeEqual } from "./crypto";
import { env } from "./env";

export function isAgent(request: Request): boolean {
  const header = request.headers.get("authorization") ?? "";
  return header.startsWith("Bearer ") && safeEqual(header.slice(7), env.agentApiKey);
}
