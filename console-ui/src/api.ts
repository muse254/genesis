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
  /**
   * Whether this registry can be wiped, read from the contract's own
   * `testMode()` rather than from configuration. The reset control is drawn
   * only when it is true, so a production registry simply has no button.
   */
  registry?: { resettable: boolean; epoch: number };
}

export interface ConfidentialScore {
  body: string;
  /** Wall-clock for the whole run. ~16s on the CRE path, almost all of it
   *  compiling TypeScript to WASM; milliseconds on the local one. */
  seconds: number;
  planeSize: number;
  pce: number;
  match: boolean;
  threshold: number;
  backend: "cre" | "local";
  /** False on every path available today. Only a deployed confidential
   *  workflow may set it true -- see `cre/backend.py`. */
  attested: boolean;
  trust: string;
  payload_digest: string;
  signature: string | null;
  signer: string | null;
}

export interface ResetResult {
  registry: string;
  epochBefore: number;
  epochAfter: number;
  /** Names of the enrolled references deleted, if any were. */
  enrolmentsCleared: string[];
  txHash: string;
  blockNumber: number;
  explorerUrl: string;
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
  /** On `no-record`: why there was nothing to find, when it can be measured. */
  diagnosis?: string | null;
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

  /**
   * Wipe the registry so the demo can be run again. Testnet only; the server
   * re-reads `testMode()` and refuses on a registry that has no reset, so a
   * stale frontend cannot spend gas on a transaction that would revert.
   *
   * `confirm` is the registry address, which the server checks. It is not
   * ceremony: this is the one control in the console that destroys work.
   */
  reset(registryAddress: string, clearEnrolments: boolean) {
    const form = new FormData();
    form.append("confirm", registryAddress);
    // The chain is half a clean slate; the enrolled references are the other
    // half and they live on disk, untouched by `resetAll`.
    form.append("clear_enrolments", String(clearEnrolments));
    return call<ResetResult>("/reset", { method: "POST", body: form });
  },

  verify(file: File) {
    const form = new FormData();
    form.append("file", file);
    return call<VerifyResult>("/verify", { method: "POST", body: form });
  },

  /**
   * Screen 07. Scores the frame where nobody holds K.
   *
   * Slow on purpose: the CRE backend compiles the workflow to WASM and runs
   * it in the simulator, which takes about sixteen seconds. The caller must
   * say so on screen or it reads as a hang.
   */
  scoreConfidential(file: File, body: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("body", body);
    return call<ConfidentialScore>("/score-confidential", { method: "POST", body: form });
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

  /**
   * Verification with progress. Same work as `verify`, reported as it runs.
   *
   * An unfamiliar image pays for all twenty-one correlations of the scale
   * search even when the answer is `no-record`, which is over a minute of
   * apparent silence.
   */
  verifyStreaming(
    file: File,
    onStep: (label: string, fraction: number) => void,
  ): Promise<VerifyResult> {
    const form = new FormData();
    form.append("file", file);
    return call<{ jobId: string }>("/verify/stream", { method: "POST", body: form }).then(
      (job) =>
        new Promise<VerifyResult>((resolve, reject) => {
          const stream = new EventSource(`${BASE}/verify/${job.jobId}/events`);
          stream.onmessage = (message) => {
            const event = JSON.parse(message.data);
            if (event.event === "step") onStep(event.label, event.fraction);
            if (event.event === "done") {
              stream.close();
              event.error ? reject(new Error(event.error)) : resolve(event.result);
            }
          };
          stream.onerror = () => {
            stream.close();
            reject(new Error("progress stream closed"));
          };
        }),
    );
  },

  /** The local catalogue. Never leaves the machine — see console/catalogue.py. */
  catalogue: () =>
    call<{
      statistics: {
        images: number; sessions: number; bodies: number; described: number;
        weakest: number | null; strongest: number | null; mean: number | null;
        first_seen: number | null; last_seen: number | null;
        perBody: { body_name: string; images: number }[];
        catalogue: string;
      };
      images: Record<string, string | number | null>[];
    }>("/catalogue"),

  describe(imageHash: string, description: string) {
    const form = new FormData();
    form.append("image_hash", imageHash);
    form.append("description", description);
    return call<{ imageHash: string }>("/catalogue/describe", { method: "POST", body: form });
  },

  /** Folders on the machine running the console, with RAW counts. */
  browse: (path?: string) =>
    call<{
      path: string;
      parent: string | null;
      frames: number;
      entries: { name: string; path: string; frames: number }[];
    }>(`/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),

  /** Display only — a browser cannot decode a CR3. Never feeds a verdict. */
  async preview(file: File, longestEdge = 720): Promise<string> {
    const form = new FormData();
    form.append("file", file);
    form.append("longest_edge", String(longestEdge));
    const response = await fetch(`${BASE}/preview`, { method: "POST", body: form });
    if (!response.ok) throw new Error(`preview: ${response.status}`);
    return URL.createObjectURL(await response.blob());
  },

  registerImage(file: File, body: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("body", body);
    return call<Record<string, unknown>>("/register-image", { method: "POST", body: form });
  },

  /**
   * A whole shoot in one transaction. `commitSession` exists because a shoot
   * is two thousand frames and one write per photograph is not affordable.
   */
  registerSession(files: File[], body: string) {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    form.append("body", body);
    return call<{
      sessionId: string;
      merkleRoot: string;
      frameCount: number;
      accepted: { name: string; imageHash: string; pce: number }[];
      refused: { name: string; pce?: number; reason: string }[];
      txHash: string;
      blockNumber: number;
      explorerUrl: string;
    }>("/register-session", { method: "POST", body: form });
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
