/**
 * Just enough EXIF to read IFD0's Make (271) and Software (305), for the
 * "this looks like an in-camera JPEG" diagnosis (`verify.ts`). Reads a JPEG's
 * APP1 segment, a PNG's eXIf chunk, or a TIFF directly. Anything malformed
 * yields nothing: a diagnosis is a courtesy, never worth an error.
 */

export interface Exif {
  make: string;
  software: string;
}

export function readExif(bytes: Uint8Array): Exif | null {
  try {
    const tiff = findTiff(bytes);
    return tiff ? readIfd0(tiff) : null;
  } catch {
    return null;
  }
}

function findTiff(b: Uint8Array): Uint8Array | null {
  if (b[0] === 0xff && b[1] === 0xd8) {
    // JPEG: walk the segments to APP1 "Exif\0\0".
    let at = 2;
    while (at + 4 <= b.length && b[at] === 0xff) {
      const marker = b[at + 1];
      const length = (b[at + 2] << 8) | b[at + 3];
      if (marker === 0xda) break; // start of scan: no more metadata
      if (marker === 0xe1 && String.fromCharCode(...b.subarray(at + 4, at + 10)) === "Exif\0\0") {
        return b.subarray(at + 10, at + 2 + length);
      }
      at += 2 + length;
    }
    return null;
  }
  if ((b[0] === 0x49 && b[1] === 0x49) || (b[0] === 0x4d && b[1] === 0x4d)) return b;
  if (b[0] === 0x89 && b[1] === 0x50) {
    // PNG: chunks after the 8-byte signature.
    let at = 8;
    while (at + 8 <= b.length) {
      const length = ((b[at] << 24) | (b[at + 1] << 16) | (b[at + 2] << 8) | b[at + 3]) >>> 0;
      if (String.fromCharCode(...b.subarray(at + 4, at + 8)) === "eXIf") return b.subarray(at + 8, at + 8 + length);
      at += 12 + length;
    }
  }
  return null;
}

function readIfd0(t: Uint8Array): Exif {
  const view = new DataView(t.buffer, t.byteOffset, t.byteLength);
  const little = t[0] === 0x49;
  const u16 = (o: number) => view.getUint16(o, little);
  const u32 = (o: number) => view.getUint32(o, little);

  const ifd = u32(4);
  const found: Record<number, string> = {};
  for (let i = 0, count = u16(ifd); i < count; i++) {
    const entry = ifd + 2 + i * 12;
    const tag = u16(entry);
    if ((tag !== 271 && tag !== 305) || u16(entry + 2) !== 2) continue; // ASCII only
    const length = u32(entry + 4);
    const at = length <= 4 ? entry + 8 : u32(entry + 8);
    found[tag] = String.fromCharCode(...t.subarray(at, at + length)).replace(/\0+$/, "").trim();
  }
  return { make: found[271] ?? "", software: found[305] ?? "" };
}
