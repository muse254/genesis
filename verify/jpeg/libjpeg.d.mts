// Types for the Emscripten module build.sh writes to verify/src/jpeg/.
// Hand-written and copied in by build.sh, because that directory is
// generated and not committed.
export interface LibJpeg {
  _decode(ptr: number, size: number): number;
  _release(): void;
  _result_pixels(): number;
  _result_w(): number;
  _result_h(): number;
  _error_message(): number;
  _malloc(size: number): number;
  _free(ptr: number): void;
  HEAPU8: Uint8Array;
  UTF8ToString(ptr: number): string;
}

export default function createLibJpeg(options?: Record<string, unknown>): Promise<LibJpeg>;
