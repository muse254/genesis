/**
 * Verdict cards, the log rail and the stage strip.
 *
 * The verdict word is the claim; the score is only a measurement (a forgery
 * can outscore a genuine photo). So PCE always renders in plain ink and
 * colour lives only on the verdict block.
 */

import { ETHERSCAN, GRAPH_STUDIO, readContractUrl, registryAddress } from "./api";
import type { Signal, Stage, Verdict, VerifyResult } from "./api";

/**
 * An on-chain value with a link to check it. Only for values actually on
 * chain. Links to the Read Contract tab because Etherscan cannot deep-link a
 * mapping read; the value sits beside it to paste in.
 */
function onChain(value: string, call: string, display?: string): string {
  const url = readContractUrl();
  const text = escape(display ?? value);
  if (!url) return `<span class="mono">${text}</span>`;
  return (
    `<a class="mono onchain" href="${escape(url)}" target="_blank" rel="noreferrer" ` +
    `title="Read ${escape(call)} on the verified contract — no wallet needed">${text} ↗</a>`
  );
}

export const el = (html: string): HTMLElement => {
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim();
  return wrap.firstElementChild as HTMLElement;
};

export const escape = (value: unknown): string =>
  String(value).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!,
  );

export const short = (hash: string, head = 10) =>
  hash.length > head + 6 ? `${hash.slice(0, head)}…${hash.slice(-4)}` : hash;

export const utc = (seconds: number) =>
  new Date(seconds * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");

/** The four verdicts, and the copy is verbatim from `docs/claims.md`. */
const VERDICTS: Record<Verdict, { word: string; blurb: string }> = {
  registered: {
    word: "REGISTERED",
    blurb:
      "The body’s owner registered this image at the time shown, and these pixels " +
      "carry that body’s fingerprint. It does not state where the light fell — " +
      "`registerImage` checks only that the body’s owner sent the transaction, and " +
      "a fingerprint can be planted. Nor what the photograph depicts, nor that it " +
      "is “authentic”.",
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
    row(
      "Descends from",
      onChain(result.derivedFrom.imageHash, "images(bytes32)", short(result.derivedFrom.imageHash)),
    );
    row(
      "Perceptual distance",
      `${result.derivedFrom.hammingDistance} of 64 bits${
        result.derivedFrom.hammingDistance === 0 ? " — identical" : ""
      }`,
    );
  }
  if (result.body) {
    row("Camera body", `<b>${escape(result.body.name ?? short(result.body.bodyId))}</b>`);
    row("Body id", onChain(result.body.bodyId, "bodies(bytes32)", short(result.body.bodyId)));
    if (result.body.commitment) {
      // Only renders inside `result.body`, which is read from the registry.
      row(
        "Fingerprint commitment",
        onChain(result.body.commitment, "bodies(bytes32)", short(result.body.commitment)),
      );
    }
    if (result.body.owner) {
      row(
        "Registered by",
        `<a class="mono" href="${escape(`${ETHERSCAN}/address/${result.body.owner}`)}" ` +
          `target="_blank" rel="noreferrer">${escape(short(result.body.owner, 8))} ↗</a>`,
      );
    }
    if (result.body.bodyCommitment && /[1-9a-f]/i.test(result.body.bodyCommitment.slice(2))) {
      // Proves nothing alone; revealed against in a dispute.
      row(
        "Camera commitment",
        onChain(result.body.bodyCommitment, "bodies(bytes32)", short(result.body.bodyCommitment)) +
          ` <small class="hint">revealed only in a dispute</small>`,
      );
    }
  }
  if (result.registration) {
    row("First registered", utc(result.registration.registeredAt));
    const registry = registryAddress();
    row(
      "On chain",
      (registry
        ? `<a class="mono" href="${escape(`${ETHERSCAN}/address/${registry}`)}" target="_blank" ` +
          `rel="noreferrer">Etherscan ↗</a> · `
        : "") +
        `<a class="mono" href="${escape(result.registration.explorerUrl)}" target="_blank" ` +
        `rel="noreferrer">Blockscout ↗</a>`,
    );
  }

  if (result.verdict === "derived" || result.verdict === "registered") {
    row(
      "Indexed by",
      `<a class="mono" href="${escape(GRAPH_STUDIO)}" target="_blank" rel="noreferrer">` +
        `The Graph ↗</a>` +
        (result.verdict === "derived"
          ? ` <small class="hint">the perceptual lookup that found the original</small>`
          : ""),
    );
  }

  // Non-negotiable on `derived`: the strongest-looking row rests on weak evidence.
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

  // A measured reason, so "no record" does not read as "not your camera".
  const diagnosis = result.diagnosis
    ? `<p class="diagnosis">${escape(result.diagnosis)}</p>`
    : "";

  return el(`
    <section class="verdict ${result.verdict}">
      <div class="vhead">${word}</div>
      <div class="vbody">${rows.join("")}</div>
      ${diagnosis}
      <p class="vfoot">${blurb}</p>
    </section>`);
}

/**
 * The PCE rail: log scale, 1 to 100,000. Scores <= 1 (negative ones are
 * common) clamp to the left edge as `< 1`.
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
        // AUC as a band on a shared 0.5-1.0 axis; near 0.5 it should look like chance.
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
