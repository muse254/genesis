/**
 * The Web Worker that runs `analyse.ts`. One request at a time per message
 * id; progress is posted back as it happens.
 */

import { analyse, loadBody, type AnalyseRequest } from "./analyse";

export type WorkerMessage =
  | { id: number; type: "load"; bodyId: string; name: string; k: Uint8Array }
  | { id: number; type: "analyse"; request: AnalyseRequest };

export type WorkerReply =
  | { id: number; step: { label: string; fraction: number } }
  | { id: number; result: unknown }
  | { id: number; error: string };

// The two members of the worker scope this file uses. (The WebWorker lib
// conflicts with DOM, which the rest of core is typed against.)
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<WorkerMessage>) => void) | null;
  postMessage(message: WorkerReply): void;
};

scope.onmessage = async ({ data }: MessageEvent<WorkerMessage>) => {
  const reply = (message: WorkerReply) => scope.postMessage(message);
  try {
    const result =
      data.type === "load"
        ? await loadBody(data.bodyId, data.name, data.k)
        : await analyse(data.request, (label, fraction) => reply({ id: data.id, step: { label, fraction } }));
    reply({ id: data.id, result });
  } catch (error) {
    reply({ id: data.id, error: error instanceof Error ? error.message : String(error) });
  }
};
