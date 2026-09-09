/**
 * The parts the design calls a system: the four verdict cards, the log rail
 * and the stage strip.
 *
 * One rule governs all of it, from board 2b: **the verdict word is the claim
 * and the score is only a measurement beside it.** A forged image scores
 * 82,190 and lands on `fingerprint-only`; a genuine degraded photograph
 * scores 37.3 and lands on `derived`. So nothing here lets magnitude, colour,
 * bar length or weight imply trust -- every PCE figure renders in identical
 * ink, and colour lives only on the verdict block.
 */

import type { Signal, Stage, Verdict, VerifyResult } from "./api";

export const el = (html: string): HTMLElement => {
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim();
  return wrap.firstElementChild as HTMLElement;
};

export const escape = (value: unknown): string =>
  String(value).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!,
  );

const short = (hash: string, head = 10) =>
  hash.length > head + 6 ? `${hash.slice(0, head)}…${hash.slice(-4)}` : hash;

export const utc = (seconds: number) =>
  new Date(seconds * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");

/** The four verdicts, and the copy is verbatim from `docs/claims.md`. */
const VERDICTS: Record<Verdict, { word: string; blurb: string }> = {
  registered: {
    word: "REGISTERED",
    blurb:
      "This states where these pixels came from and who signed for them, when. " +
      "It does not state what the photograph depicts, or that it is “authentic”.",
  },
  derived: {
    word: "DERIVED",
    blurb:
      "A registration exists on chain, signed by the body’s owner, and this " +
      "file’s perceptual hash matches it. Nothing else.",
  },
  "fingerprint-only": {
    word: "FINGERPRINT ONLY",
    blurb:
      "Not a pass. These pixels carry that body’s fingerprint and nobody has " +
      "registered this image. A fingerprint can be planted: a single RAW file " +
      "off a camera is enough to stamp it onto an image the camera never took, " +
      "at a distortion no eye can see. Only a registration signed by the " +
      "body’s owner means anything here.",
  },
  "no-record": {
    word: "NO RECORD",
    blurb:
      "Genesis holds no matching record. That is the entire finding — it does " +
      "not mean the image is fabricated, and it does not mean it was not taken " +
      "on a camera. Most photographs in the world are unregistered.",
  },
};

export function verdictCard(result: VerifyResult): HTMLElement {
  const { word, blurb } = VERDICTS[result.verdict];
  const rows: string[] = [];
  const row = (label: string, value: string) =>
    rows.push(
      `<div class="vrow"><span class="label">${escape(label)}</span><span>${value}</span></div>`,
    );

  if (result.derivedFrom) {
    row("Descends from", `<span class="mono">${escape(short(result.derivedFrom.imageHash))}</span>`);
    row(
      "Perceptual distance",
      `${result.derivedFrom.hammingDistance} of 64 bits${
        result.derivedFrom.hammingDistance === 0 ? " — identical" : ""
      }`,
    );
  }
  if (result.body) {
    row("Camera body", `<b>${escape(result.body.name ?? short(result.body.bodyId))}</b>`);
    if (result.body.ensName && result.body.owner) {
      row(
        "Identity",
        `<span class="mono">${escape(result.body.ensName)}</span> → ` +
          `<span class="mono">${escape(short(result.body.owner, 8))}</span>`,
      );
    }
  }
  if (result.registration) {
    row("First registered", utc(result.registration.registeredAt));
    row(
      "Transaction",
      `<a class="mono" href="${escape(result.registration.explorerUrl)}" target="_blank" ` +
        `rel="noreferrer">view on the explorer ↗</a>`,
    );
  }

  // The sub-threshold sentence is required on `derived` and is the one piece
  // of copy the handoff calls non-negotiable. Hiding it would let the
  // strongest-looking row rest on the weakest evidence.
  const clears = result.pce >= result.threshold;
  row(
    "Pixels",
    `PCE ${result.pce.toFixed(1)} (threshold ${result.threshold})` +
      (clears
        ? ""
        : ` — <b>below threshold; the pixels do not carry this claim.</b>` +
          (result.verdict === "derived"
            ? " The perceptual hash and the chain carry it."
            : "")),
  );

  return el(`
    <section class="verdict ${result.verdict}">
      <div class="vhead">${word}</div>
      <div class="vbody">${rows.join("")}</div>
      <p class="vfoot">${blurb}</p>
    </section>`);
}

/**
 * The PCE rail: logarithmic, 1 to 100,000, never a 0-100 bar.
 *
 * The handoff's formula is `log10(pce)/5`, which is undefined at or below
 * zero -- and negative scores are ordinary here, a different camera lands at
 * -30.9 and -44.0 routinely. Those clamp to the left edge and are labelled
 * `< 1`. The rail starts at 1 because that is where a log scale can start,
 * not because scores do.
 */
export function rail(marks: { pce: number; label: string }[], idle = false): HTMLElement {
  const position = (pce: number) =>
    pce <= 1 ? 0 : Math.min(100, (Math.log10(pce) / 5) * 100);

  const decades = [1, 10, 100, 1000, 10000, 100000]
    .map((value) => {
      const left = (Math.log10(value) / 5) * 100;
      return `<span class="tick" style="left:${left}%"><i></i><em>${value.toLocaleString()}</em></span>`;
    })
    .join("");

  const markers = marks
    .map(
      (mark) =>
        `<span class="marker" style="left:${position(mark.pce)}%" title="${escape(mark.label)}">
           <i></i><em>${mark.pce <= 1 ? "&lt; 1" : mark.pce.toLocaleString(undefined, { maximumFractionDigits: 1 })}</em>
         </span>`,
    )
    .join("");

  return el(`
    <div class="rail ${idle ? "idle" : ""}">
      <div class="line"></div>
      ${decades}
      <span class="threshold" style="left:${(Math.log10(100) / 5) * 100}%">
        <i></i><em>THRESHOLD 100</em>
      </span>
      ${markers}
    </div>`);
}

/** Stage strip. Visual weight encodes authority, and only stage 3 decides. */
export function stageStrip(stages: Stage[]): HTMLElement {
  const signals = (value: Stage["result"]) => {
    if (!Array.isArray(value) || value.length === 0) {
      return `<p class="none">no signals available — not calibrated</p>`;
    }
    return (value as Signal[])
      .map((signal) => {
        // AUC drawn as a band on a shared 0.5-1.0 axis. Overlapping bands are
        // the honest picture: at 0.517 the band spans nearly the whole axis,
        // which is what "chance" looks like and is worth showing.
        const auc = signal.auc ?? 0.5;
        const left = ((0.5 - 0.5) / 0.5) * 100;
        const width = ((auc - 0.5) / 0.5) * 100;
        return `
          <div class="signal">
            <span class="name mono">${escape(signal.signal)}</span>
            <span class="value mono">${signal.value === null ? "—" : signal.value.toFixed(4)}</span>
            <span class="band"><i style="left:${left}%;width:${Math.max(width, 2)}%"></i>
              <b style="left:${width}%"></b></span>
            <span class="auc mono">${signal.auc === null ? "n/a" : `AUC ${signal.auc.toFixed(3)}`}</span>
          </div>`;
      })
      .join("");
  };

  return el(`
    <div class="stages">
      ${stages
        .map(
          (stage) => `
        <section class="stage ${stage.stage === 3 ? "decides" : ""}">
          <div class="label">STAGE ${stage.stage} · ${escape(stage.name)}</div>
          <p class="asks">${escape(stage.asks)}</p>
          ${
            stage.stage === 2
              ? `<div class="advisory">ADVISORY — DECIDES NOTHING</div>${signals(stage.result)}`
              : `<div class="result">${escape(stage.result ?? "—")}</div>`
          }
          <p class="decides">${escape(stage.decides)}</p>
        </section>`,
        )
        .join("")}
    </div>`);
}
