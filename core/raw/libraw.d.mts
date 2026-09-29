// Types for the Emscripten module build.sh writes to core/src/raw/.
// Hand-written and copied in by build.sh, because that directory is
// generated and not committed.
export interface LibRawModule {
  _raw_open(ptr: number, size: number): number;
  _raw_close(): void;
  _raw_error(): number;
  _raw_visible(): number;
  _raw_width(): number;
  _raw_height(): number;
  _raw_pattern_size(): number;
  _raw_pattern_at(y: number, x: number): number;
  _raw_color_visible(y: number, x: number): number;
  _raw_black(c: number): number;
  _raw_white(): number;
  _raw_make(): number;
  _raw_model(): number;
  _raw_body_serial(): number;
  _raw_libraw_version(): number;
  _malloc(size: number): number;
  _free(ptr: number): void;
  HEAPU8: Uint8Array;
  HEAPU16: Uint16Array;
  UTF8ToString(ptr: number): string;
}

export default function createLibRaw(options?: Record<string, unknown>): Promise<LibRawModule>;
