/** The Web Worker that runs `analyse.ts`; progress is posted back per message id. */

import { analyse, loadBody, type AnalyseRequest } from "./analyse";
import { warm } from "./hashes";

export type WorkerMessage =
  | { id: number; type: "load"; bodyId: string; name: string; k: Uint8Array }
  | { id: number; type: "analyse"; request: AnalyseRequest }
  | { id: number; type: "warm" };

export type WorkerReply =
  | { id: number; step: { label: string; fraction: number } }
  | { id: number; result: unknown }
  | { id: number; error: string };

// Hand-typed: the WebWorker lib conflicts with DOM, which the rest of core uses.
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<WorkerMessage>) => void) | null;
  postMessage(message: WorkerReply): void;
};

scope.onmessage = async ({ data }: MessageEvent<WorkerMessage>) => {
  const reply = (message: WorkerReply) => scope.postMessage(message);
  try {
    const result =
      data.type === "warm"
        ? await warm()
        : data.type === "load"
          ? await loadBody(data.bodyId, data.name, data.k)
          : await analyse(data.request, (label, fraction) => reply({ id: data.id, step: { label, fraction } }));
    reply({ id: data.id, result });
  } catch (error) {
    reply({ id: data.id, error: error instanceof Error ? error.message : String(error) });
  }
};
