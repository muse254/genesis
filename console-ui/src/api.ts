/**
 * Typed client for the console API (`console/app.py`). Shapes mirror the
 * server; server decisions pass through untouched, never re-judged here.
 * Verification runs in `verifier.ts` on `@genesis/core`.
 */

/** Desktop injects its backend port (`desktop/src-tauri/src/lib.rs`); else env or default. */
export const BASE =
  (window as { __GENESIS_CONSOLE__?: string }).__GENESIS_CONSOLE__ ??
  import.meta.env.VITE_CONSOLE_URL ??
  "http://127.0.0.1:8100";


export type { Verdict, Stage, Signal } from "@genesis/core";
export type { VerifyResult } from "./verifier";

export interface Check {
  check: string;
  measured: string;
  expected: string;
  go: boolean;
  remedy?: string;
}

export interface BodyStatus {
  name: string;
  bodyId: string;
  /** Whether the registry has a record for it. Enrolled is not registered
   *  (`resetAll` clears the registration but keeps the fingerprint). */
  registered: boolean;
}

export interface State {
  ready: boolean;
  checks: Check[];
  bodies: string[];
  bodyStatus?: BodyStatus[];
  threshold: number;
  chain: {
    chainId?: number;
    chainName?: string;
    onExpectedChain?: boolean;
    blockNumber?: number;
    registry?: string | null;
    etherscan?: string;
    blockscout?: string;
  };
  /** The contract's own `testMode()`, not config; gates the reset control. */
  registry?: { resettable: boolean; epoch: number };
  /** What core/ needs to read the chain through `/rpc` and the index through `/subgraph`. */
  verify?: { chain: string; registry: string | null; explorer: string; subgraph: boolean };
}

/** Where a claim can be checked by someone who does not trust this console. */
export interface ReferenceLink {
  label: string;
  url: string;
}


export interface ResetResult {
  registry: string;
  epochBefore: number;
  epochAfter: number;
  /** Names of the enrolled references deleted, if any were. */
  enrolmentsCleared: string[];
  /** Archive rows removed. Always cleared, or withdrawn work would show as registered. */
  archiveRowsCleared: number;
  txHash: string;
  blockNumber: number;
  explorerUrl: string;
  links?: ReferenceLink[];
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

/**
 * The registry from the last `/state`, for the verdict card's links. Null
 * until then: a link built from a guessed address is worse than none.
 */
let seenRegistry: string | null = null;

export const registryAddress = (): string | null => seenRegistry;

/** Explorer for the server's chain, from `/state` (`console/chain.py` owns it); Sepolia until then. */
export let ETHERSCAN = "https://sepolia.etherscan.io";

/** Where the indexed events can be queried. `console/chain.py` agrees. */
export const GRAPH_STUDIO = "https://thegraph.com/studio/subgraph/genesis";

/**
 * The Read Contract tab, where anyone can call `bodies`/`images` without a
 * wallet (Etherscan cannot deep-link a mapping read).
 */
export const readContractUrl = (): string | null =>
  seenRegistry ? `${ETHERSCAN}/address/${seenRegistry}#readContract` : null;

export const api = {
  state: async () => {
    const state = await call<State>("/state");
    seenRegistry = state.chain?.registry ?? null;
    if (state.chain?.etherscan) ETHERSCAN = state.chain.etherscan;
    return state;
  },

  /**
   * Wipe a test registry; the server re-checks `testMode()`. `confirm` is the
   * registry address, checked server-side: this control destroys work.
   */
  reset(registryAddress: string, clearEnrolments: boolean) {
    const form = new FormData();
    form.append("confirm", registryAddress);
    // Enrolled references live on disk, untouched by `resetAll`.
    form.append("clear_enrolments", String(clearEnrolments));
    return call<ResetResult>("/reset", { method: "POST", body: form });
  },

  /** `registerBody` is a race (a leaked reference lets someone claim the id), so it comes first. */
  registerBody(name: string, bodyCommitment: string) {
    const form = new FormData();
    form.append("name", name);
    form.append("body_commitment", bodyCommitment);
    return call<{ bodyId: string; bodyCommitment: string; txHash: string; blockNumber: number;
                  explorerUrl: string; links?: ReferenceLink[] }>(
      "/register-body", { method: "POST", body: form },
    );
  },

  /** Bring back a camera enrolled before, from its fingerprint file. */
  importBody(file: File) {
    const form = new FormData();
    form.append("file", file);
    return call<{ bodyId: string; name: string; registered: boolean | null }>(
      "/bodies/import", { method: "POST", body: form },
    );
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
  /** Display only — a browser cannot decode a CR3. Never feeds a verdict. */
  async preview(file: File, longestEdge = 720): Promise<string> {
    const form = new FormData();
    form.append("file", file);
    form.append("longest_edge", String(longestEdge));
    const response = await fetch(`${BASE}/preview`, { method: "POST", body: form });
    if (!response.ok) throw new Error(`preview: ${response.status}`);
    return URL.createObjectURL(await response.blob());
  },

  /** Register an image, streaming each phase with the server's timestamps. */
  registerImageStreaming(
    file: File,
    body: string,
    onStep: (step: { phase?: string; label: string; at: string; elapsed: number }) => void,
  ) {
    const form = new FormData();
    form.append("file", file);
    form.append("body", body);
    return call<{ jobId: string }>("/register-image/stream", { method: "POST", body: form })
      .then(
        (job) =>
          new Promise<{
            imageHash: string; perceptualHash: string; bodyId: string; pce: number;
            registeredAt: number; txHash: string; blockNumber: number;
            explorerUrl: string; links?: ReferenceLink[];
          }>((resolve, reject) => {
            const stream = new EventSource(`${BASE}/register-image/${job.jobId}/events`);
            // EventSource fires `onerror` on a normal close too; only a drop
            // before the job reports done is a real failure.
            let settled = false;
            stream.onmessage = (message) => {
              const event = JSON.parse(message.data);
              if (event.event === "step") {
                onStep(event);
                return;
              }
              if (event.event === "done") {
                settled = true;
                stream.close();
                if (event.error) reject(new Error(String(event.error)));
                else resolve(event.result);
              }
            };
            stream.onerror = () => {
              if (settled) return;
              stream.close();
              reject(new Error("the progress stream dropped before the job finished"));
            };
          }),
      );
  },

  registerImage(file: File, body: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("body", body);
    return call<{
      imageHash: string;
      perceptualHash: string;
      bodyId: string;
      pce: number;
      registeredAt: number;
      txHash: string;
      blockNumber: number;
      explorerUrl: string;
      links?: ReferenceLink[];
    }>("/register-image", { method: "POST", body: form });
  },

  /** A whole shoot in one transaction. */
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
  links?: ReferenceLink[];
    }>("/register-session", { method: "POST", body: form });
  },

  /** Progress arrives per frame; enrolment reads forty 24-megapixel RAWs. */
  /**
   * Enrol from picked frames (`File[]`) or a server-side folder path (for
   * scripts, and to avoid uploading half a gigabyte).
   */
  enrol(
    from: File[] | string,
    name: string,
    onEvent: (event: Record<string, unknown>) => void,
    onUpload?: (loaded: number, total: number) => void,
  ) {
    const form = new FormData();
    if (typeof from === "string") form.append("folder", from);
    else for (const file of from) form.append("files", file);
    form.append("name", name);

    // XHR, not fetch: fetch cannot report upload progress, and this upload
    // is large and otherwise silent.
    const upload = new Promise<{ jobId: string; frames: number }>((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `${BASE}/enrol`);
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onUpload?.(event.loaded, event.total);
      });
      request.addEventListener("load", () => {
        let body: Record<string, unknown> = {};
        try {
          body = JSON.parse(request.responseText);
        } catch {
          /* a non-JSON body is still a failure; the status carries it */
        }
        if (request.status >= 200 && request.status < 300) {
          resolve(body as unknown as { jobId: string; frames: number });
        } else {
          reject(new Error(String(body.detail ?? `${request.status} ${request.statusText}`)));
        }
      });
      request.addEventListener("error", () =>
        reject(new Error("the console did not answer — is it still running?")),
      );
      request.send(form);
    });

    return upload.then((job) => {
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
