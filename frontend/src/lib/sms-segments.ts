/**
 * SMS encoding detection and segment counting – mirror of backend/app/shared/sms_segments.py.
 * Both implementations are tested against backend/tests/fixtures/sms_segments.json.
 */

const GSM7_BASIC =
  "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?" +
  "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
const GSM7_EXTENSION = "^{}\\[~]|€\f";

const BASIC = new Set(Array.from(GSM7_BASIC));
const EXT = new Set(Array.from(GSM7_EXTENSION));

export type Encoding = "GSM7" | "UCS2";

export interface SegmentInfo {
  encoding: Encoding;
  length: number;
  segments: number;
  perSegment: number;
  remaining: number;
  nonGsmChars: string[];
}

export function detectEncoding(text: string): Encoding {
  for (const c of Array.from(text)) {
    if (!BASIC.has(c) && !EXT.has(c)) return "UCS2";
  }
  return "GSM7";
}

export function analyze(text: string): SegmentInfo {
  const encoding = detectEncoding(text);
  let length: number;
  let single: number;
  let multi: number;
  let nonGsmChars: string[] = [];
  if (encoding === "GSM7") {
    length = Array.from(text).reduce((n, c) => n + (EXT.has(c) ? 2 : 1), 0);
    single = 160;
    multi = 153;
  } else {
    length = text.length; // JS strings are UTF-16 code units, exactly what UCS-2 counts
    single = 70;
    multi = 67;
    const seen = new Set<string>();
    for (const c of Array.from(text)) if (!BASIC.has(c) && !EXT.has(c)) seen.add(c);
    nonGsmChars = Array.from(seen).slice(0, 20);
  }
  let segments: number;
  let perSegment: number;
  if (length === 0) {
    segments = 0;
    perSegment = single;
  } else if (length <= single) {
    segments = 1;
    perSegment = single;
  } else {
    perSegment = multi;
    segments = Math.ceil(length / multi);
  }
  return { encoding, length, segments, perSegment, remaining: Math.max(segments, 1) * perSegment - length, nonGsmChars };
}
