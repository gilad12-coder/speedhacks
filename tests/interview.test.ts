import { describe, expect, it } from "vitest";
import { InterviewError, parseToolCall } from "@/lib/interview";

describe("parseToolCall", () => {
  it("reads a question with choices", () => {
    const step = parseToolCall("ask", JSON.stringify({ message: "Do you work from home?", choices: [{ label: "Most days" }, { label: "Never" }] }));
    expect(step).toEqual({ kind: "ask", text: "Do you work from home?", choices: [{ label: "Most days" }, { label: "Never" }] });
  });

  it("drops unknown features and keeps each feature in one list", () => {
    const step = parseToolCall(
      "finish",
      JSON.stringify({ message: "Thanks!", mustHaves: ["In-unit laundry", "Rooftop pool"], niceToHaves: ["In-unit laundry", "Parking"], dealBreakers: [], wishes: ["Quiet street"] }),
    );
    expect(step).toMatchObject({ kind: "finish", mustHaves: ["In-unit laundry"], niceToHaves: ["Parking"], wishes: ["Quiet street"] });
  });

  it("rejects malformed replies", () => {
    expect(() => parseToolCall("ask", "{not json")).toThrow(InterviewError);
    expect(() => parseToolCall("delete_everything", "{}")).toThrow(InterviewError);
  });
});
