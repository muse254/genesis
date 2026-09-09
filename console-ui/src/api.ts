/**
 * Typed client for the console API (`console/app.py`, spec
 * `docs/console-server.md`).
 *
 * Shapes mirror the server exactly. Where the server decides something --
 * which verdict, whether a pre-flight row passes -- this client carries the
 * answer through untouched. The frontend renders; it never evaluates. A
 * second opinion here is a second place to be wrong, and the two would
 * eventually disagree about the same image.
 */

const BASE = import.meta.env.VITE_CONSOLE_URL ?? "http://127.0.0.1:8100";

export type Verdict = "registered" | "derived" | "fingerprint-only" | "no-record";

export interface Check {
  check: string;
  measured: string;
  expected: string;
  go: boolean;
  remedy?: string;
}

export interface State {
  ready: boolean;
  checks: Check[];
  bodies: string[];
  threshold: number;
  chain: { chainId?: number; blockNumber?: number; registry?: string | null };
  ensParent: string | null;
}

export interface Signal {
  signal: string;
  value: number | null;
  auc: number | null;
}

export interface Stage {
  stage: number;
  name: string;
  asks: string;
  result: string | Signal[] | null;
  decides: string;
}

export interface VerifyResult {
  verdict: Verdict;
  pce: number;
  threshold: number;
  method: string | null;
  orientation: string | null;
  imageHash: string;
  perceptualHash: string;
  body: {
    bodyId: string;
    name?: string;
    owner?: string | null;
    commitment?: string | null;
    revoked?: boolean | null;
    ensName?: string | null;
  } | null;
  registration: {
    registeredAt: number;
    modificationLevel: number;
    pceAtRegistration: number;
    explorerUrl: string;
  } | null;
  derivedFrom: { imageHash: string; hammingDistance: number; matchedBy: string } | null;
  consistency: Record<string, number | boolean | null> | null;
  stages: Stage[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON body is still a failure; the status is enough */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  state: () => call<State>("/state"),

  verify(file: File) {
    const form = new FormData();
    form.append("file", file);
    return call<VerifyResult>("/verify", { method: "POST", body: form });
  },

  /** Screen 04. Quality has no default here either -- see `/degrade`'s docstring. */
  async degrade(file: File, longestEdge: number, quality: number): Promise<File> {
    const form = new FormData();
    form.append("file", file);
    form.append("longest_edge", String(longestEdge));
    form.append("quality", String(quality));
    const response = await fetch(`${BASE}/degrade`, { method: "POST", body: form });
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    return new File([blob], "degraded.jpg", { type: "image/jpeg" });
  },

  registerImage(file: File, body: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("body", body);
    return call<Record<string, unknown>>("/register-image", { method: "POST", body: form });
  },

  /** Progress arrives per frame; enrolment reads forty 24-megapixel RAWs. */
  enrol(folder: string, name: string, onEvent: (event: Record<string, unknown>) => void) {
    const form = new FormData();
    form.append("folder", folder);
    form.append("name", name);
    return call<{ jobId: string; frames: number }>("/enrol", { method: "POST", body: form })
      .then((job) => {
        const stream = new EventSource(`${BASE}/enrol/${job.jobId}/events`);
        stream.onmessage = (message) => {
          const event = JSON.parse(message.data);
          onEvent(event);
          if (event.event === "done") stream.close();
        };
        return job;
      });
  },
};
