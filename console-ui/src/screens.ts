/**
 * The presenter console screens; one file because they share the drop-slot
 * and result grammar. Progress is determinate wherever the server reports
 * real steps, and never faked where it does not.
 */

import {
  api,
  ETHERSCAN,
  type Check,
  type ReferenceLink,
  type State,
  type VerifyResult,
} from "./api";
import { el, escape, rail, short, stageStrip, verdictCard } from "./components";
import { verifyStreaming } from "./verifier";

type Render = (host: HTMLElement) => void;

/** Clear this screen's result without a reload (which would lose pre-flight state). */
function clearButton(host: HTMLElement, render: Render): HTMLElement {
  const button = el(`<button class="clear" title="Clear (C)">Clear</button>`);
  button.addEventListener("click", () => render(host));
  return button;
}

/** A fixed-aspect slot. Never bundle real camera files: one full-resolution
 *  photograph is enough to recover a fingerprint (`docs/security.md`). */
function dropSlot(hint: string, onFile: (file: File) => void): HTMLElement {
  const slot = el(`
    <label class="slot">
      <input type="file" accept="image/*,.cr3,.dng,.CR3,.DNG" hidden />
      <span>${escape(hint)}</span>
    </label>`);
  const input = slot.querySelector("input")!;
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) onFile(file);
  });
  return slot;
}

/** What a browser can decode itself. Everything else goes to `/preview`. */
const NATIVE = /\.(jpe?g|png|webp|gif|avif|bmp)$/i;

/**
 * Show the photograph being worked on. Never await it before the real work:
 * a server-side RAW preview can take ~90 s and is display-only.
 */
async function showImage(slot: HTMLElement, file: File, degraded = false) {
  slot.classList.add("filled");
  const cls = degraded ? "degraded" : "";

  if (NATIVE.test(file.name)) {
    slot.innerHTML = `<img src="${URL.createObjectURL(file)}" class="${cls}" alt="" />`;
    return;
  }

  slot.innerHTML = `<span class="developing pulse mono">developing ${escape(file.name)}…</span>`;
  try {
    const url = await api.preview(file);
    slot.innerHTML = `<img src="${url}" class="${cls}" alt="" />`;
  } catch {
    // Preview failed; still show the file is loaded.
    slot.innerHTML = `<span class="developing mono">${escape(file.name)}<br/>
      <small>no preview — RAW decode unavailable</small></span>`;
  }
}

/** Score a file and render the verdict, with determinate progress per correlation. */
async function scored(
  host: HTMLElement,
  file: File,
  compare?: { pce: number; label: string },
) {
  host.querySelector(".result-area")!.innerHTML = `
    <div class="stepper">
      <div class="bar"><i style="width:2%"></i></div>
      <p class="step mono">starting…</p>
      <p class="elapsed mono"></p>
    </div>`;

  const bar = host.querySelector(".stepper .bar i") as HTMLElement;
  const step = host.querySelector(".stepper .step")!;
  const elapsed = host.querySelector(".stepper .elapsed")!;
  const started = Date.now();
  const timer = setInterval(() => {
    elapsed.textContent = `${((Date.now() - started) / 1000).toFixed(1)}s elapsed`;
  }, 100);

  try {
    const result = await verifyStreaming(file, (label, fraction) => {
      bar.style.width = `${Math.max(2, Math.round(fraction * 100))}%`;
      step.textContent = label;
    });
    clearInterval(timer);
    const marks = [{ pce: result.pce, label: "this file" }];
    if (compare) marks.push(compare);
    const area = host.querySelector(".result-area")!;
    area.innerHTML = "";
    area.append(rail(marks));
    area.append(verdictCard(result));
    area.append(stageStrip(result.stages));
    return result;
  } catch (error) {
    clearInterval(timer);
    host.querySelector(".result-area")!.innerHTML = "";
    host.querySelector(".result-area")!.append(
      failure("SCORING FAILED", (error as Error).message, "Nothing already on screen is withdrawn."),
    );
    return undefined;
  }
}

/** Errors fail in words, never a stack trace, and withdraw nothing. */
function failure(heading: string, detail: string, standing: string): HTMLElement {
  return el(`
    <div class="failure">
      <div class="fhead">${escape(heading)}</div>
      <p class="mono detail">${escape(detail)}</p>
      <p class="standing">${escape(standing)}</p>
    </div>`);
}

/**
 * The reset control, only on a registry that can be wiped. Two-step, and the
 * second step shows the address: the mistake to prevent is wiping the wrong one.
 */
function drawReset(host: HTMLElement, state: State): void {
  const zone = host.querySelector(".reset-zone") as HTMLElement | null;
  if (!zone) return;

  if (!state.registry?.resettable) {
    zone.innerHTML = "";
    return;
  }

  const address = state.chain.registry ?? "";
  const epoch = state.registry.epoch;
  zone.innerHTML = `
    <div class="reset">
      <div class="reset-head">
        <b>Test registry</b>
        <span class="mono">epoch ${epoch}</span>
      </div>
      <p>This deployment can be wiped, which is how the demo is rehearsed more
         than once. Registration dates here mean nothing and the verify page
         says so. A production registry has no such control.</p>
      ${
        state.bodies.length
          ? `<label class="reset-also">
        <input type="checkbox" class="reset-enrolments" checked />
        <span>also clear the ${state.bodies.length} enrolled
          ${state.bodies.length === 1 ? "reference" : "references"} on this machine
          — needed to rehearse from step 1, and <b>not reversible</b>: the frames
          survive, but the same K only comes back from the same frames</span>
      </label>`
          : ""
      }
      <button class="reset-go">Wipe every record</button>
      <div class="reset-out"></div>
    </div>`;

  const button = zone.querySelector(".reset-go") as HTMLButtonElement;
  const out = zone.querySelector(".reset-out") as HTMLElement;
  let armed = false;

  button.addEventListener("click", async () => {
    if (!armed) {
      armed = true;
      button.textContent = `Confirm — wipe ${address.slice(0, 10)}…`;
      button.classList.add("armed");
      out.textContent = "Click again to send the transaction. Anything else cancels.";
      // Disarm on a click elsewhere, so a stray press cannot wipe it.
      setTimeout(() => {
        document.addEventListener(
          "click",
          () => {
            if (!armed) return;
            armed = false;
            button.textContent = "Wipe every record";
            button.classList.remove("armed");
            out.textContent = "";
          },
          { once: true },
        );
      }, 0);
      return;
    }

    armed = false;
    button.disabled = true;
    button.textContent = "wiping…";
    button.classList.remove("armed");
    try {
      const alsoEnrolments =
        (zone.querySelector(".reset-enrolments") as HTMLInputElement | null)?.checked ?? false;
      const result = await api.reset(address, alsoEnrolments);
      out.innerHTML = `<span class="ok">Wiped.</span> epoch ${result.epochBefore} → ${result.epochAfter} ·
        <a href="${escape(result.explorerUrl)}" target="_blank" rel="noreferrer">${escape(result.txHash.slice(0, 12))}…</a>
        ${
          result.enrolmentsCleared.length
            ? `<br>Cleared ${escape(result.enrolmentsCleared.join(", "))} — enrol again to continue.`
            : ""
        }
        ${
          result.archiveRowsCleared
            ? `<br>Archive emptied: ${escape(result.archiveRowsCleared)} ${
                result.archiveRowsCleared === 1 ? "record" : "records"
              } described registrations the wipe withdrew.`
            : ""
        }
        <br>The index follows within a block or two. Nothing is registered now.`;
      // In place, not a redraw, so the transaction hash stays on screen.
      const label = zone.querySelector(".reset-head .mono");
      if (label) label.textContent = `epoch ${result.epochAfter}`;
    } catch (error) {
      out.innerHTML = `<span class="bad">${escape((error as Error).message)}</span>`;
    } finally {
      button.disabled = false;
      button.textContent = "Wipe every record";
    }
  });
}

/** Where anyone can check a claim without trusting this console. Server-assembled. */
function referenceLinks(links?: ReferenceLink[]): string {
  if (!links?.length) return "";
  const items = links
    .map(
      (link) =>
        `<li><a href="${escape(link.url)}" target="_blank" rel="noreferrer">${escape(
          link.label,
        )}</a></li>`,
    )
    .join("");
  return `<ul class="refs">${items}</ul>`;
}

/**
 * Register the enrolled body when the registry has no record of it. Comes
 * first: `registerBody` is a race a leaked reference could win.
 */
async function drawBodyStep(host: HTMLElement, ledger: HTMLElement): Promise<void> {
  const state = await api.state().catch(() => null);
  const pending = state?.bodyStatus?.find((b) => !b.registered);
  if (!pending) return;

  const panel = el(`
    <div class="body-step">
      <p><b>${escape(pending.name)}</b> is enrolled on this machine and the registry has
         no record of it. A photograph cannot attach to a body the chain has never heard
         of, so this comes first.</p>
      <label>Camera commitment <small class="hint">optional · from
        <span class="mono">python -m ingest commit-body</span></small>
        <input class="body-commitment" placeholder="0x… (32 bytes), or leave blank"
               spellcheck="false" />
      </label>
      <p class="hint">A keyed hash of make, model and serial. It cannot be added
         later: its value is that it predates any dispute.</p>
      <button class="body-go">Register this body</button>
      <div class="body-out"></div>
    </div>`);
  ledger.prepend(panel);

  const button = panel.querySelector(".body-go") as HTMLButtonElement;
  const out = panel.querySelector(".body-out") as HTMLElement;

  button.addEventListener("click", async () => {
    const camera = (panel.querySelector(".body-commitment") as HTMLInputElement).value.trim();
    if (camera && !/^(0x)?[0-9a-fA-F]{64}$/.test(camera)) {
      out.innerHTML = `<span class="bad">The camera commitment must be 32 bytes of hex, or blank.</span>`;
      return;
    }
    button.disabled = true;
    button.textContent = "registering…";
    try {
      const receipt = await api.registerBody(pending.name, camera);
      panel.innerHTML = `
        <p><b>${escape(pending.name)}</b> registered as
           <span class="mono">${escape(short(receipt.bodyId))}</span>, block
           ${escape(receipt.blockNumber)}.</p>
        <p class="mono txlink"><a href="${escape(receipt.explorerUrl)}" target="_blank"
           rel="noreferrer">view transaction ↗</a></p>
        ${referenceLinks(receipt.links)}`;
    } catch (error) {
      out.innerHTML = `<span class="bad">${escape((error as Error).message)}</span>`;
      button.disabled = false;
      button.textContent = "Register this body";
    }
  });
}

/** 00 · Pre-flight. The go/no-go gate, checked before recording starts. */
export const preflight: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Pre-flight</h1>
    <p class="lede">Every one of these can fail on camera. Checked now, not during.
       Press <b>P</b> to re-run.</p>
    <div class="preflight"><div class="table">loading…</div><div class="gate"></div></div>
    <div class="reset-zone"></div>`;

  const draw = (state: State) => {
    const rows = state.checks
      .map(
        (check: Check) => `
        <tr class="${check.go ? "" : "bad"}">
          <td>${escape(check.check)}</td>
          <td class="mono">${escape(check.measured)}</td>
          <td class="mono expected">${escape(check.expected)}</td>
          <td class="go">${check.go ? "GO" : "NO-GO"}</td>
        </tr>
        ${check.remedy ? `<tr class="remedy"><td colspan="4">→ ${escape(check.remedy)}</td></tr>` : ""}`,
      )
      .join("");

    host.querySelector(".table")!.innerHTML = `
      <table>
        <thead><tr><th>CHECK</th><th>MEASURED</th><th>EXPECTED</th><th>GO</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    drawReset(host, state);

    const failing = state.checks.filter((c) => !c.go);
    host.querySelector(".gate")!.innerHTML = state.ready
      ? `<div class="go-block"><div class="word">GO</div>
           <p>${state.bodies.length} enrolled ${state.bodies.length === 1 ? "body" : "bodies"} · threshold ${state.threshold}</p></div>`
      : `<div class="nogo-block"><div class="word">NO-GO</div>
           <p>${failing.length} check${failing.length === 1 ? "" : "s"} failing.</p>
           <p class="mono first">${escape(failing[0]?.check ?? "")}</p>
           <p class="remedy">${escape(failing[0]?.remedy ?? "")}</p></div>`;
  };

  api
    .state()
    .then(draw)
    .catch((error) => {
      host.querySelector(".table")!.innerHTML = "";
      host.querySelector(".table")!.append(
        failure("CONSOLE UNREACHABLE", error.message, "Start it: uvicorn console.app:app --port 8100"),
      );
    });
};

/** 01 · Enrol. A file picker, then a determinate per-frame progress grid. */
export const enrol: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Enrol a camera body</h1>
    <p class="lede">Forty-odd RAW frames from an archive that already exists.
       K never leaves this machine; only its commitment goes on chain.</p>
    <div class="two-col">
      <div class="left">
        <div class="picker">
          <label class="slot pick">
            <input type="file" multiple accept=".cr3,.CR3,.dng,.DNG,.arw,.ARW,.nef,.NEF,.raf,.RAF,.rw2,.RW2,image/*" hidden />
            <span>Choose the RAW frames</span>
          </label>
          <form class="enrol-form" hidden>
            <p class="picked mono"></p>
            <p class="warn" hidden></p>
            <input name="name" placeholder="body name, e.g. r10" required />
            <button>Enrol these frames</button>
          </form>
        </div>
      </div>
      <div class="right"><div class="grid"></div><div class="enrol-side"></div></div>
    </div>`;

  const picker = host.querySelector(".picker")!;
  const grid = host.querySelector(".grid")!;
  const side = host.querySelector(".enrol-side")!;

  /** The OS file dialog. Frames are uploaded, but only over localhost. */
  const input = picker.querySelector("input[type=file]") as HTMLInputElement;
  const form = picker.querySelector(".enrol-form") as HTMLFormElement;
  const picked = picker.querySelector(".picked") as HTMLElement;
  const warn = picker.querySelector(".warn") as HTMLElement;
  let chosen: File[] = [];

  const RAW = /\.(cr3|cr2|dng|arw|nef|raf|rw2|orf|pef|srw)$/i;

  input.addEventListener("change", () => {
    const all = Array.from(input.files ?? []);
    chosen = all.filter((file) => RAW.test(file.name));
    const skipped = all.length - chosen.length;

    form.hidden = chosen.length === 0;
    const bytes = chosen.reduce((sum, file) => sum + file.size, 0);
    picked.textContent = chosen.length
      ? `${chosen.length} RAW ${chosen.length === 1 ? "frame" : "frames"} · ${(
          bytes / 1e9
        ).toFixed(2)} GB${skipped ? ` · ${skipped} non-RAW ignored` : ""}`
      : "";

    // Gate A asks for 40-50; fewer still works (no cliff), so only a caution.
    const short = chosen.length > 0 && chosen.length < 40;
    warn.hidden = !(short || (chosen.length === 0 && all.length > 0));
    warn.textContent = chosen.length === 0 && all.length > 0
      ? "None of those are RAW. A developed JPEG has already been through the camera's noise reduction, which is what removes the fingerprint."
      : `Gate A asks for 40–50 frames; ${chosen.length} will still enrol, less sharply.`;

    if (chosen.length === 0 && all.length > 0) form.hidden = true;
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = String(new FormData(form).get("name")).trim();
    if (!name || chosen.length === 0) return;
    picker.querySelector(".slot")!.classList.add("filled");
    run(chosen, name);
  });

  const run = (from: File[] | string, name: string) => {
    let total = 0;

    // Synchronously, before the long upload, so it does not read as a hang.
    const bytes = typeof from === "string" ? 0 : from.reduce((sum, f) => sum + f.size, 0);
    const frameCount = typeof from === "string" ? 0 : from.length;
    grid.innerHTML = "";
    side.innerHTML = `
      <div class="uploading">
        <p class="label">sending</p>
        <div class="display up-count">${frameCount || "…"}</div>
        <p class="mono up-note">${
          bytes
            ? `reading ${(bytes / 1e9).toFixed(2)} GB from disk…`
            : "reading frames from the server’s disk…"
        }</p>
        <div class="up-bar"><span></span></div>
        <p class="note">Nothing is estimated until every frame has arrived.</p>
      </div>`;

    const bar = side.querySelector(".up-bar span") as HTMLElement | null;
    const note = side.querySelector(".up-note") as HTMLElement | null;

    api
      .enrol(
        from,
        name,
        (e) => {
        if (e.event === "start") {
          total = Number(e.frames);
          // Upload done; the per-frame grid takes over.
          grid.innerHTML = Array.from({ length: total }, () => `<i class="cell"></i>`).join("");
          side.innerHTML = `<div class="display">0 / ${total}</div>
            <p class="label">frames</p><p class="mono">starting…</p>`;
        }
        if (e.event === "frame") {
          grid.querySelectorAll(".cell").forEach((cell, index) => {
            cell.className =
              index < Number(e.index) ? "cell done"
                : index === Number(e.index) ? "cell live pulse" : "cell";
          });
          side.innerHTML = `<div class="display">${e.index} / ${total}</div>
            <p class="label">frames</p><p class="mono">${escape(e.name)}</p>`;
        }
        if (e.event === "done") {
          const result = e.result as Record<string, string> | null;
          side.innerHTML = "";
          if (e.error) {
            side.append(failure("ENROLMENT FAILED", String(e.error), "No fingerprint was written."));
            return;
          }
          side.innerHTML = `<div class="commitment">
              <p class="label">commitment</p>
              <p class="mono hash">${escape(result?.commitment ?? "")}</p>
              <p class="note">The fingerprint itself stays on this machine; only this
                 commitment goes on chain — and it is <b>not there yet</b>. Registering
                 the body on step 02 is what puts it in the registry, and from then on
                 it can be read back by anyone.</p>
            </div>`;
        }
        },
        (loaded, totalBytes) => {
          const share = totalBytes ? loaded / totalBytes : 0;
          if (bar) bar.style.width = `${Math.round(share * 100)}%`;
          if (note) {
            note.textContent =
              share >= 1
                ? "all frames received — starting the estimator…"
                : `${(loaded / 1e9).toFixed(2)} of ${(totalBytes / 1e9).toFixed(2)} GB sent`;
          }
        },
      )
      .catch((error) => {
        side.innerHTML = "";
        side.append(failure("ENROLMENT FAILED", error.message, "No fingerprint was written."));
      });
  };

};

/** 02 · Register. The only screen that writes to the chain. */
export const register: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Register a photograph</h1>
    <p class="lede">Scored first and refused below the threshold before anything is
       signed — a photograph the pixels do not support never reaches the chain.</p>
    <div class="two-col">
      <div class="left"></div>
      <div class="right"><div class="ledger-area"></div><div class="result-area"></div></div>
    </div>`;

  const left = host.querySelector(".left")!;
  const ledger = host.querySelector(".ledger-area")!;
  host.querySelector(".title")!.append(clearButton(host, register));

  // Without this, `registerImage` reverts `unknown body` after a wipe.
  void drawBodyStep(host, ledger as HTMLElement);

  // One file registers an ImageRecord; many commit one session root.
  const many = el(`
    <label class="bulk">
      <input type="file" multiple accept="image/*,.cr3,.dng,.CR3,.DNG" hidden />
      <span>or select a whole shoot — one Merkle root, one transaction</span>
    </label>`);
  const bulkInput = many.querySelector("input")!;
  bulkInput.addEventListener("change", async () => {
    const files = Array.from(bulkInput.files ?? []);
    if (files.length === 0) return;
    if (files.length === 1) return;         // one file belongs on the single path

    const bodyName = (await api.state().catch(() => null))?.bodies[0] ?? "";
    if (!bodyName) {
      ledger.append(failure("NO ENROLLED BODY", "The scorer holds no fingerprint.",
                            "Run step 01 first."));
      return;
    }
    ledger.innerHTML = `<ol class="ledger">
      <li>scoring ${files.length} frames against <b>${escape(bodyName)}</b></li>
      <li class="pulse">building the Merkle root and committing</li></ol>`;
    try {
      const session = await api.registerSession(files, bodyName);
      ledger.innerHTML = `<ol class="ledger">
        <li>${session.frameCount} frames accepted${
          session.refused.length ? `, ${session.refused.length} refused` : ""
        }</li>
        <li>one root committed in block ${escape(session.blockNumber)}</li>
      </ol>
      <p class="mono small">root ${escape(session.merkleRoot.slice(0, 22))}…</p>
      ${
        session.refused.length
          ? `<ul class="refused">${session.refused
              .map((r) => `<li class="mono">${escape(r.name)} — ${escape(r.reason)}</li>`)
              .join("")}</ul>`
          : ""
      }
      <p class="mono txlink"><a href="${escape(session.explorerUrl)}" target="_blank"
         rel="noreferrer">view transaction ↗</a></p>
      ${referenceLinks(session.links)}`;
    } catch (error) {
      ledger.innerHTML = "";
      ledger.append(failure("SESSION FAILED", (error as Error).message,
                            "Nothing was signed."));
    }
  });

  left.append(
    dropSlot("Drop the RAW to register", async (file) => {
      void showImage(left.querySelector(".slot")!, file);

      let bodyName = "";
      try {
        const state = await api.state();
        bodyName = state.bodies[0] ?? "";
      } catch {
        /* the failure below reports it */
      }
      if (!bodyName) {
        ledger.append(failure("NO ENROLLED BODY", "The scorer holds no fingerprint.",
                              "Run step 01 first, or check GENESIS_REFERENCES."));
        return;
      }

      // Timestamped real phases: most of the wait is the PRNU search, not the chain.
      ledger.innerHTML = `<ol class="steps"></ol><p class="elapsed mono"></p>`;
      const steps = ledger.querySelector(".steps") as HTMLElement;
      const clock = ledger.querySelector(".elapsed") as HTMLElement;
      const began = Date.now();
      const ticking = setInterval(() => {
        clock.textContent = `${((Date.now() - began) / 1000).toFixed(1)}s elapsed · this is PRNU scoring, not the chain`;
      }, 100);

      // "7 of 21" progress lines replace each other rather than stacking.
      let searchRow: HTMLElement | null = null;

      try {
        const receipt = await api.registerImageStreaming(file, bodyName, (step) => {
          const time = step.at.slice(11, 23);
          const line =
            `<span class="stamp mono">${escape(time)}</span>` +
            `<span class="took mono">+${escape(step.elapsed.toFixed(1))}s</span>` +
            `<span class="what">${escape(step.label)}</span>`;

          if (step.phase === "scoring" && /\bof\b/.test(step.label)) {
            if (!searchRow) {
              searchRow = document.createElement("li");
              searchRow.className = "step live";
              steps.append(searchRow);
            }
            searchRow.innerHTML = line;
            return;
          }
          steps.querySelectorAll(".step.live").forEach((el) => el.classList.remove("live"));
          const row = document.createElement("li");
          row.className = "step live";
          row.innerHTML = line;
          steps.append(row);
          if (step.phase !== "scoring") searchRow = null;
        });
        clearInterval(ticking);
        clock.textContent = `${((Date.now() - began) / 1000).toFixed(1)}s total`;
        steps.querySelectorAll(".step.live").forEach((el) => el.classList.remove("live"));

        ledger.insertAdjacentHTML(
          "beforeend",
          `<p class="mono txlink"><a href="${escape(receipt.explorerUrl)}" target="_blank"
             rel="noreferrer">view transaction ↗</a></p>
           ${referenceLinks(receipt.links)}`,
        );

        // Read it back as a verifier would rather than trusting the receipt.
        await scored(host, file);
      } catch (error) {
        clearInterval(ticking);
        ledger.innerHTML = "";
        const message = (error as Error).message;
        ledger.append(
          /below/i.test(message)
            ? failure("REFUSED — BELOW THRESHOLD", message,
                      "Nothing was signed. The pixels do not support the claim.")
            : failure("REGISTRATION FAILED", message,
                      "Nothing already on screen is withdrawn."),
        );
      }
    }),
  );
  left.append(many);
};

/** 03 · Negative. Must read as "no record", never as an accusation. */
export const negative: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">A photograph from a different camera</h1>
    <p class="lede">Same model, different body — the case that decides the threshold.</p>
    <div class="two-col"><div class="left"></div><div class="right result-area"></div></div>`;
  host.querySelector(".title")!.append(clearButton(host, negative));
  const left = host.querySelector(".left")!;
  left.append(
    dropSlot("Drop a frame from another camera", async (file) => {
      void showImage(left.querySelector(".slot")!, file);
      await scored(host, file);
    }),
  );
};

/** 04 · Survival. The money shot: strip, resize, re-encode, and it still resolves. */
export const survival: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Strip it, resize it, re-encode it</h1>
    <p class="lede">Metadata removed, 1800px longest edge, JPEG quality 95.
       Quality is stated because the claim dies between q95 and q80.</p>
    <div class="survival">
      <div class="pair"><div class="orig"></div><div class="copy"></div></div>
      <div class="mid"></div>
    </div>
    <div class="result-area"></div>`;

  host.querySelector(".title")!.append(clearButton(host, survival));
  const orig = host.querySelector(".orig")!;
  orig.append(
    dropSlot("Drop the registered photograph", async (file) => {
      void showImage(orig.querySelector(".slot")!, file);
      const mid = host.querySelector(".mid")!;
      mid.innerHTML = `<ol class="ledger">
        <li>strip metadata</li><li>resize to 1800px</li><li>re-encode q95</li>
        <li class="pulse">re-score</li></ol>`;
      try {
        const degraded = await api.degrade(file, 1800, 95);
        const copy = host.querySelector(".copy")!;
        copy.innerHTML = `<div class="slot filled"></div>`;
        void showImage(copy.querySelector(".slot")!, degraded, true);
        mid.querySelector(".pulse")?.classList.remove("pulse");
        await scored(host, degraded);
      } catch (error) {
        host.querySelector(".result-area")!.append(
          failure("SCORER UNREACHABLE", (error as Error).message,
                  "The degraded copy is saved; every result already on screen stands."),
        );
      }
    }),
  );
};

/** 05 · Verdict. Any image, the full card. */
export const verdict: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Verify</h1>
    <p class="lede">Drop any photograph. We say whether its owner registered it —
       or that we have no record.</p>
    <div class="two-col"><div class="left"></div><div class="right result-area"></div></div>`;
  host.querySelector(".title")!.append(clearButton(host, verdict));
  const left = host.querySelector(".left")!;
  left.append(
    dropSlot("Drop any image", async (file) => {
      void showImage(left.querySelector(".slot")!, file);
      await scored(host, file);
    }),
  );
};

/**
 * 06 · Archive. Maps on-chain hashes back to local files. Local only: paths
 * and captions never go near the network.
 */
export const archive: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Archive</h1>
    <p class="lede">Everything this machine has registered. Held locally: the chain
       has the hashes, this has what they were.</p>
    <div class="stats"></div>
    <div class="catalogue">loading…</div>`;
  host.querySelector(".title")!.append(clearButton(host, archive));

  api
    .catalogue()
    .then(({ statistics: st, images }) => {
      const figure = (value: number | null, digits = 0) =>
        value === null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: digits });

      host.querySelector(".stats")!.innerHTML = `
        <div class="stat"><span class="display">${st.images}</span><span class="label">registered</span></div>
        <div class="stat"><span class="display">${st.sessions ?? 0}</span><span class="label">sessions</span></div>
        <div class="stat"><span class="display">${st.bodies ?? 0}</span><span class="label">bodies</span></div>
        <div class="stat"><span class="display">${st.described}</span><span class="label">described</span></div>
        <div class="stat wide">
          <span class="label">PCE across the archive</span>
          <span class="mono">${figure(st.weakest, 1)} weakest · ${figure(st.mean, 1)} mean · ${figure(st.strongest, 1)} strongest</span>
        </div>`;

      if (images.length === 0) {
        host.querySelector(".catalogue")!.innerHTML =
          `<p class="empty">Nothing registered yet. Screen 02 fills this.</p>`;
        return;
      }

      host.querySelector(".catalogue")!.innerHTML = `
        <table class="archive">
          <thead><tr><th>FILE</th><th>PCE</th><th>IMAGE HASH</th><th>DESCRIPTION</th></tr></thead>
          <tbody>${images
            .map(
              (row) => `
              <tr>
                <td>${escape(row.file_name ?? "—")}
                  ${row.file_path ? `<br/><small class="mono">${escape(row.file_path)}</small>` : ""}</td>
                <td class="mono num">${row.pce === null ? "—" : Number(row.pce).toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>
                <td>${
                  row.tx_hash
                    ? // The registering tx is the most precise place to check.
                      `<a class="mono" href="${escape(`${ETHERSCAN}/tx/${row.tx_hash}`)}"
                          target="_blank" rel="noreferrer"
                          title="the transaction that registered this image"
                       >${escape(String(row.image_hash ?? "").slice(0, 14))}… ↗</a>`
                    : `<span class="mono">${escape(String(row.image_hash ?? "").slice(0, 14))}…</span>`
                }</td>
                <td><input class="desc" data-hash="${escape(row.image_hash)}"
                     value="${escape(row.description ?? "")}"
                     placeholder="add a note…" /></td>
              </tr>`,
            )
            .join("")}</tbody>
        </table>`;

      // Save on blur: no save click per row.
      host.querySelectorAll("input.desc").forEach((input) =>
        input.addEventListener("blur", async () => {
          const field = input as HTMLInputElement;
          field.classList.remove("saved", "failed");
          try {
            await api.describe(field.dataset.hash!, field.value);
            field.classList.add("saved");
          } catch {
            field.classList.add("failed");
          }
        }),
      );
    })
    .catch((error) => {
      host.querySelector(".catalogue")!.innerHTML = "";
      host.querySelector(".catalogue")!.append(
        failure("CATALOGUE UNAVAILABLE", error.message, "Registrations still work."),
      );
    });
};

export const SCREENS: { id: string; label: string; render: Render }[] = [
  { id: "preflight", label: "00 PRE-FLIGHT", render: preflight },
  { id: "enrol", label: "01 ENROL", render: enrol },
  { id: "register", label: "02 REGISTER", render: register },
  { id: "negative", label: "03 NEGATIVE", render: negative },
  { id: "survival", label: "04 SURVIVAL", render: survival },
  { id: "verdict", label: "05 VERDICT", render: verdict },
  { id: "archive", label: "06 ARCHIVE", render: archive },
];

export type { VerifyResult };
