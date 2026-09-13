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

export interface BodyStatus {
  name: string;
  bodyId: string;
  /** Whether the registry has a record for it. Enrolled is not registered:
   *  an image cannot attach to a body the chain has never heard of, and a
   *  `resetAll` clears the registration while leaving the fingerprint. */
  registered: boolean;
}

export interface State {
  ready: boolean;
  checks: Check[];
  bodies: string[];
  bodyStatus?: BodyStatus[];
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

/** Where a claim can be checked by someone who does not trust this console. */
export interface ReferenceLink {
  label: string;
  url: string;
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
  /** Archive rows removed. Always cleared: every row describes a chain record
   *  the wipe just withdrew, so keeping them would present withdrawn work as
   *  registered. */
  archiveRowsCleared: number;
  txHash: string;
  blockNumber: number;
  explorerUrl: string;
  links?: ReferenceLink[];
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
  links?: ReferenceLink[];
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

/**
 * The registry the console is pointed at, remembered from the last `/state`.
 *
 * The verdict card renders on-chain values and should say where to check
 * them, but it is a pure render function with no access to the server. This
 * is the smallest way to give it one, and it is deliberately null until a
 * state call has happened -- a link built from a guessed address is worse
 * than no link.
 */
let seenRegistry: string | null = null;

export const registryAddress = (): string | null => seenRegistry;

/** Sepolia, matching `console/chain.py`. */
export const ETHERSCAN = "https://sepolia.etherscan.io";

/**
 * Where a bytes32 the registry holds can be read back by anyone.
 *
 * Etherscan cannot deep-link a mapping read with its argument, so this points
 * at the verified contract's Read Contract tab -- which needs no wallet, and
 * is where `bodies(bytes32)` and `images(bytes32)` can be called with the
 * value beside it. `docs/claims.md` says a registration is verifiable by
 * anyone without taking our word for it; this is the "how".
 */
export const readContractUrl = (): string | null =>
  seenRegistry ? `${ETHERSCAN}/address/${seenRegistry}#readContract` : null;

export const api = {
  state: async () => {
    const state = await call<State>("/state");
    seenRegistry = state.chain?.registry ?? null;
    return state;
  },

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
   * Demo step 2a, and the step the console never had. `registerBody` is a
   * race -- `bodyId` derives from SHA-256(K), so a leaked reference lets
   * someone else claim the slot -- which is why it comes before anything else.
   */
  registerBody(name: string, ensLabel: string) {
    const form = new FormData();
    form.append("name", name);
    form.append("ens_label", ensLabel);
    return call<{ bodyId: string; ensName: string; txHash: string; blockNumber: number;
                  explorerUrl: string; links?: ReferenceLink[] }>(
      "/register-body", { method: "POST", body: form },
    );
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
    // Typed rather than `Record<string, unknown>`: the screen renders the
    // score and the links off this, and an untyped bag hides a rename.
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
  links?: ReferenceLink[];
    }>("/register-session", { method: "POST", body: form });
  },

  /** Progress arrives per frame; enrolment reads forty 24-megapixel RAWs. */
  /**
   * Enrol from frames the operator picked, or from a server-side folder.
   *
   * `File[]` is the console path: the operating system's own dialog, which is
   * where a photographer already knows how to find their frames. A string is
   * a path on the machine running the API, kept for scripts and the offline
   * run -- forty RAW frames is half a gigabyte and nobody should upload it
   * twice.
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

    // XHR rather than fetch, for the one thing fetch cannot do: report how
    // far an upload has got. Forty RAW frames is half a gigabyte, and the
    // server says nothing at all until the last byte has arrived and the job
    // starts -- so with fetch the screen sits silent through the longest part
    // of the operation and looks hung. `docs/console-server.md` already had
    // to learn this once about verification.
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
