/**
 * `analyse` through the real WASM modules, in-process, against what the
 * Python verify path returned for the same synthetic inputs
 * (`python -m fingerprint.dump_search_fixtures`).
 *
 * The Rust port itself is parity-tested by cargo (`search_parity.rs`); this
 * checks the TypeScript around it: the bindings, the candidate ordering,
 * the RAW path, the signals payload, and the progress the desktop shows.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

import { inProcessEngine } from "../src/engine";
import { diagnose, stages } from "../src/verify";

const fixtures = join(__dirname, "..", "..", "rust", "genesis-prnu", "tests", "fixtures", "search");
const manifest = JSON.parse(readFileSync(join(fixtures, "manifest.json"), "utf8"));
const file = (name: string) => new Uint8Array(readFileSync(join(fixtures, name)));
const engine = inProcessEngine({ prnuWasm: readFileSync(join(__dirname, "..", "src", "wasm", "genesis_prnu_wasm_bg.wasm")) });

const close = (got: number, want: number, rel = 0.02) => Math.abs(got - want) <= rel * Math.max(Math.abs(want), 1);

beforeAll(async () => {
  await engine.loadBody("r10", "synthetic-r10", file("k.npz"));
});

describe("scoring against an enrolled body matches Python", () => {
  it.each(manifest.cases.map((c: { name: string }) => [c.name, c]))("%s", async (_name, c: any) => {
    const analysis = await engine.analyse({ bytes: file(c.file), name: c.file, bodies: ["r10"] });
    const best = analysis.candidates[0];

    expect(best).toMatchObject({
      bodyId: "r10",
      name: "synthetic-r10",
      path: c.result.path,
      orientation: c.result.orientation,
      scale: c.result.scale ?? null,
      borderStripped: c.result.borderStripped ?? null,
      turned: c.result.turned ?? null,
    });
    expect(close(best.pce, c.result.pce)).toBe(true);
    expect(analysis.threshold).toBe(100);
  });

  it("the RAW path scores the decoded planes, not the developed pixels", async () => {
    const raw = { rgb: new Uint8Array(0), width: 0, height: 0, planes: {} as Record<string, Uint8Array> };
    const developed = await engine.analyse({ bytes: file(manifest.raw.developed), name: "x.png", bodies: [] });
    // Developed pixels, as /raw/decode would send them.
    const png = file(manifest.raw.developed);
    const { decode } = await import("../src/hashes");
    const pixels = await decode(png, "x.png");
    Object.assign(raw, pixels, { planes: { none: file(manifest.raw.planes) } });

    const analysis = await engine.analyse({ bytes: new Uint8Array(0), name: "frame.CR3", bodies: ["r10"], raw });
    expect(analysis.candidates[0].path).toBe("aligned");
    expect(close(analysis.candidates[0].pce, manifest.raw.pce)).toBe(true);
    // The pixel hash of a RAW is the hash of its development.
    expect(analysis.imageHash).toBe(developed.imageHash);
    // RAW gets no delivered-pixel signals, as in Python.
    expect(analysis.signals).toMatchObject({ resamplingPeak: null, detail: null, tooSoftToMeasure: null });
    expect(analysis.signals!.effectiveStrength).not.toBeNull();
  });
});

describe("signals", () => {
  it("match Python for the best body, with its payload shape", async () => {
    const analysis = await engine.analyse({ bytes: file("aligned.png"), name: "aligned.png", bodies: ["r10"] });
    const s = manifest.signals;
    expect(analysis.signals).toMatchObject({ calibrated: false, bodyConsistency: null, pooledTriangle: null });
    expect(close(analysis.signals!.effectiveStrength!, s.effectiveStrength)).toBe(true);
    expect(close(analysis.signals!.resamplingPeak!, s.resamplingPeak, 1e-6)).toBe(true);
    expect(analysis.signals!.detail).toBe(Math.round(s.detail * 10) / 10);
    expect(analysis.signals!.tooSoftToMeasure).toBe(s.detail < 200);
  });

  it("are absent with no bodies, as on the web page", async () => {
    const analysis = await engine.analyse({ bytes: file("aligned.png"), name: "aligned.png", bodies: [] });
    expect(analysis.candidates).toEqual([]);
    expect(analysis.signals).toBeNull();
  });
});

describe("progress", () => {
  it("reports every search step, weighted as the desktop showed it", async () => {
    const steps: [string, number][] = [];
    await engine.analyse({ bytes: file("resized.png"), name: "resized.png", bodies: ["r10"] }, (l, f) => steps.push([l, f]));

    const searching = steps.filter(([l]) => l.startsWith("searching"));
    expect(searching).toHaveLength(21);
    expect(searching[0]).toEqual(["searching scale and orientation — 1 of 21 (rot 0 scale 1.000)", 0.231]);
    expect(searching.at(-1)![1]).toBe(0.85);
    expect(steps.find(([l]) => l === "extracting the noise residual")![1]).toBe(0.15);
  });
});

describe("ports of the Python reporting", () => {
  it("stages match consistency.stages field for field", () => {
    expect(
      stages({
        matched: true,
        registered: false,
        signals: { effectiveStrength: 0.25, resamplingPeak: 4.0, bodyConsistency: null },
        path: "delivered",
      }),
    ).toEqual(manifest.stages);
  });

  it.each(manifest.diagnose.map((d: { file: string }) => [d.file, d]))("diagnose(%s) matches _diagnose", (name, d: any) => {
    expect(diagnose(file(name as string), name as string, null)).toBe(d.diagnosis);
  });

  it("diagnoses a soft frame before reading EXIF, and says nothing about RAW", () => {
    const soft = { tooSoftToMeasure: true, detail: 7.7 } as any;
    expect(diagnose(file("exif_lightroom.jpg"), "a.jpg", soft)).toMatch(/median tile 7.7/);
    expect(diagnose(file("exif_camera.jpg"), "a.CR3", null)).toBeNull();
  });
});
