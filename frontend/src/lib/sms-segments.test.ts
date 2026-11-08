import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { analyze } from "./sms-segments";

interface Case {
  name: string;
  text: string;
  encoding: string;
  length: number;
  segments: number;
}

const fixtures: Case[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../../backend/tests/fixtures/sms_segments.json"), "utf-8"),
);

describe("sms segments (shared fixtures with backend)", () => {
  for (const c of fixtures) {
    it(c.name, () => {
      const info = analyze(c.text);
      expect(info.encoding).toBe(c.encoding);
      expect(info.length).toBe(c.length);
      expect(info.segments).toBe(c.segments);
    });
  }
});
