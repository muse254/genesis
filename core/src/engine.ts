/**
 * Where the pixel work runs. The pages use a Web Worker so scoring never
 * blocks the UI; tests and Node scripts run the same `analyse` in-process.
 * Both satisfy one interface, so `verify.ts` does not know which it has.
 */

import { analyse, loadBody, type AnalyseRequest, type Analysis, type OnStep } from "./analyse";
import { warm, type Loaders } from "./hashes";
import type { WorkerMessage, WorkerReply } from "./worker";

export interface Engine {
  /**
   * Start loading the WASM now. Optional to call; a page calls it on load so
   * the first photo doesn't pay for compiling ~1.8 MB of WASM (measured: the
   * first 24 MP JPEG took 6.5 s cold, 1.3 s warm).
   */
  warm(): Promise<void>;
  /** Parse a body's K once. Resolves with the crop a RAW decode must use for it. */
  loadBody(id: string, name: string, k: Uint8Array): Promise<{ crop: number | null }>;
  analyse(request: AnalyseRequest, onStep?: OnStep): Promise<Analysis>;
}

/** `Omit<T, "id">` for each member of a union, not the union as a whole. */
type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;

/** The pages' engine: a module worker, started on first use. */
export function workerEngine(): Engine {
  let worker: Worker | undefined;
  let next = 0;
  const pending = new Map<number, { resolve(v: unknown): void; reject(e: Error): void; onStep?: OnStep }>();

  function call<T>(message: WithoutId<WorkerMessage>, transfer: Transferable[], onStep?: OnStep): Promise<T> {
    if (!worker) {
      worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = ({ data }: MessageEvent<WorkerReply>) => {
        const entry = pending.get(data.id);
        if (!entry) return;
        if ("step" in data) return entry.onStep?.(data.step.label, data.step.fraction);
        pending.delete(data.id);
        if ("error" in data) entry.reject(new Error(data.error));
        else entry.resolve(data.result);
      };
      worker.onerror = (event) => {
        for (const entry of pending.values()) entry.reject(new Error(event.message || "the verification worker failed"));
        pending.clear();
      };
    }
    const id = next++;
    return new Promise<T>((resolve, reject) => {
      pending.set(id, { resolve: resolve as (v: unknown) => void, reject, onStep });
      worker!.postMessage({ ...message, id }, transfer);
    });
  }

  return {
    warm: () => call({ type: "warm" }, []),
    // K is copied, not transferred: the caller may keep its bytes.
    loadBody: (bodyId, name, k) => call({ type: "load", bodyId, name, k }, []),
    analyse: (request, onStep) => call({ type: "analyse", request }, [], onStep),
  };
}

/** The same work on the calling thread, for tests and Node. */
export function inProcessEngine(loaders: Loaders = {}): Engine {
  return {
    warm: () => warm(loaders),
    loadBody: (id, name, k) => loadBody(id, name, k, loaders),
    analyse: (request, onStep) => analyse(request, onStep, loaders),
  };
}
