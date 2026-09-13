/**
 * The six screens. One file, because they share the drop-slot and result
 * grammar and splitting them would mean re-deriving it five times.
 *
 * Every screen has the same four states: idle, working, a verdict, or an
 * error. Working states are determinate wherever the server gives us
 * something to count -- `/enrol` streams per frame, so that one is honest.
 * `/verify` and `/degrade` return once, so those show elapsed against a
 * typical figure and no fake sub-steps (`docs/console-server.md`).
 */

import {
  api,
  ETHERSCAN,
  type Check,
  type ConfidentialScore,
  type ReferenceLink,
  type State,
  type VerifyResult,
} from "./api";
import { el, escape, rail, stageStrip, verdictCard } from "./components";

type Render = (host: HTMLElement) => void;

/**
 * Clear everything this screen is holding.
 *
 * A presenter runs each screen several times in a take, and a result left
 * from the previous attempt beside a fresh photograph is how a demo shows the
 * wrong number to an audience. Clearing is one action, not a page reload,
 * because a reload also loses the pre-flight state.
 */
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
 * Show the photograph being worked on.
 *
 * RAW is the whole difficulty: a browser cannot decode a CR3, so an `<img>`
 * pointing at one renders nothing and reports nothing -- the slot just stays
 * empty, which is how the register screen came to show no image at all. The
 * server develops it instead, and only for display.
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
    // A preview is cosmetic. Say the file is loaded rather than leaving a
    // slot that looks like nothing happened.
    slot.innerHTML = `<span class="developing mono">${escape(file.name)}<br/>
      <small>no preview — RAW decode unavailable</small></span>`;
  }
}

/**
 * Score a file and render the verdict, showing real progress while it runs.
 *
 * Determinate, not a spinner. The server reports each stage and, inside the
 * scale search, each of its twenty-one correlations -- which is where the
 * wall clock goes. An unfamiliar image pays for all of them even when the
 * answer is `no-record`, so the slowest case is the one that most needs to
 * look like it is working.
 */
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
    const result = await api.verifyStreaming(file, (label, fraction) => {
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
 * The reset control, drawn only on a registry that says it can be wiped.
 *
 * `bodyId` derives from SHA-256(K), so the same camera always reaches the same
 * id and `registerBody` refuses a duplicate forever. Rehearsing the demo twice
 * used to mean redeploying; this is the button that replaces that.
 *
 * Two-step on purpose. It is the only control in the console that destroys
 * work, and the second step shows the registry address because the mistake
 * worth preventing is wiping the wrong one -- not wiping at all.
 */
function drawReset(host: HTMLElement, state: State): void {
  const zone = host.querySelector(".reset-zone") as HTMLElement | null;
  if (!zone) return;

  if (!state.registry?.resettable) {
    // A production registry has no reset, so it gets no button and no
    // explanation of one. Silence is the correct UI for a missing capability.
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
      // Disarming on a click elsewhere means a stray press cannot destroy a
      // registry two seconds before recording.
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
      // Updated in place rather than by redrawing the panel: a redraw would
      // replace this element and take the transaction hash with it, which is
      // the one thing the operator may need after a destructive action.
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

/**
 * 07 · Confidential. The same score, computed where nobody holds K.
 *
 * `scoring/app.py` is the trust hole by design -- it holds the reference and
 * you take its word for a PCE. This screen is the answer: published
 * algorithm, private reference, and a score that crosses back out of the
 * enclave on its own.
 *
 * The screen exists to be honest about three things at once, and losing any
 * of them would make it a worse demo rather than a shorter one:
 *   - it really runs, through the CRE CLI, compiling to WASM on every run;
 *   - it takes about sixteen seconds, which is why the stages are narrated;
 *   - it is **not attested**, because the simulator is not a real enclave.
 */
export const confidential: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Scored where nobody holds K</h1>
    <p class="lede">The reference is never sent and never published — only a residual
       crop is scored against it, and only a score comes back. RAW only: a developed
       JPEG has no photosite lattice left.</p>
    <div class="two-col"><div class="left"></div><div class="right result-area"></div></div>`;
  host.querySelector(".title")!.append(clearButton(host, confidential));

  const left = host.querySelector(".left")!;
  const right = host.querySelector(".right")! as HTMLElement;

  left.append(
    dropSlot("Drop a RAW frame", async (file) => {
      await showImage(left.querySelector(".slot")!, file);
      await runConfidential(right, file);
    }),
  );
};

/**
 * Sixteen seconds with no output is indistinguishable from a crash, and this
 * repository has already been bitten by that once on the verify path. The
 * stages are real and in order; the timings are what `docs/cre.md` measured,
 * so the bar is honest rather than decorative.
 */
async function runConfidential(right: HTMLElement, file: File): Promise<void> {
  const stages = [
    ["extracting the noise residual", 1200],
    ["cropping to 256² and quantising to int8", 600],
    ["compiling the workflow to WASM", 11000],
    ["running the handler in the enclave", 3000],
  ] as const;

  right.innerHTML = `<div class="conf-run"><div class="conf-stage mono"></div>
    <div class="conf-bar"><span></span></div></div>`;
  const label = right.querySelector(".conf-stage")!;
  const bar = right.querySelector(".conf-bar span") as HTMLElement;

  let cancelled = false;
  void (async () => {
    let elapsed = 0;
    const total = stages.reduce((sum, [, ms]) => sum + ms, 0);
    for (const [text, ms] of stages) {
      if (cancelled) return;
      label.textContent = `${text}…`;
      const start = elapsed;
      const step = 100;
      for (let t = 0; t < ms && !cancelled; t += step) {
        await new Promise((r) => setTimeout(r, step));
        bar.style.width = `${Math.min(99, ((start + t) / total) * 100)}%`;
      }
      elapsed += ms;
    }
  })();

  try {
    const result = await api.scoreConfidential(file, "r10");
    cancelled = true;
    bar.style.width = "100%";
    right.innerHTML = confidentialCard(result);
  } catch (error) {
    cancelled = true;
    right.innerHTML = "";
    right.append(
      failure(
        "The confidential path did not run",
        (error as Error).message,
        "Nothing is claimed and nothing was sent. `GENESIS_CONFIDENTIAL_BACKEND=local` " +
          "computes the same number without the CLI.",
      ),
    );
  }
}

function confidentialCard(r: ConfidentialScore): string {
  const verdict = r.match ? "clears the threshold" : "does not clear the threshold";
  return `
    <div class="conf-card ${r.match ? "ok" : "no"}">
      <h2>${escape(r.pce.toFixed(1))} <small>(threshold ${escape(r.threshold)})</small></h2>
      <p class="conf-verdict">${escape(verdict)}</p>
      <dl>
        <div class="row"><dt>Computed by</dt><dd>${escape(r.backend)}${
          r.backend === "cre" ? " — CRE simulator" : " — in this process"
        }</dd></div>
        <div class="row"><dt>Took</dt><dd>${escape(r.seconds)}s</dd></div>
        <div class="row"><dt>Sent</dt><dd>${escape(r.planeSize)}² per CFA plane, int8 — never K</dd></div>
        <div class="row"><dt>Payload digest</dt><dd class="mono">${escape(
          r.payload_digest.slice(0, 24),
        )}…</dd></div>
        <div class="row"><dt>Attested</dt><dd><b>${r.attested ? "yes" : "no"}</b></dd></div>
      </dl>
      <p class="caveat">${escape(r.trust)}</p>
      <p class="caveat">This does nothing about forgery. An enclave would score a planted
         fingerprint faithfully and sign it — confidential compute protects the reference
         from the verifier, and the attack happens before the pixels arrive.</p>
    </div>`;
}

/**
 * The places a claim can be checked by someone who does not trust this
 * console. `docs/claims.md` says a registration is verifiable by anyone
 * against the registry without taking our word for it, and a claim nobody is
 * shown how to check is a claim taken on trust.
 *
 * Server-assembled: the console knows the addresses, and a second copy in the
 * frontend is a second thing to keep in step with a redeployment.
 */
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
 * Register the enrolled body, when the registry has no record of it.
 *
 * Drawn only when it is needed: once the body is on chain this is noise, and
 * the screen is about photographs. `registerBody` is a race -- `bodyId`
 * derives from SHA-256(K), so anyone holding a leaked reference can claim the
 * slot and lock the photographer out permanently -- which is why it comes
 * before anything else rather than being offered as an afterthought.
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
      <label>ENS label
        <input class="ens-label" value="${escape(pending.name)}" spellcheck="false" />
      </label>
      <button class="body-go">Register this body</button>
      <div class="body-out"></div>
    </div>`);
  ledger.prepend(panel);

  const button = panel.querySelector(".body-go") as HTMLButtonElement;
  const out = panel.querySelector(".body-out") as HTMLElement;

  button.addEventListener("click", async () => {
    const label = (panel.querySelector(".ens-label") as HTMLInputElement).value.trim();
    if (!label) {
      out.innerHTML = `<span class="bad">The ENS label cannot be empty.</span>`;
      return;
    }
    button.disabled = true;
    button.textContent = "registering…";
    try {
      const receipt = await api.registerBody(pending.name, label);
      panel.innerHTML = `
        <p><b>${escape(pending.name)}</b> registered as
           <span class="mono">${escape(receipt.ensName)}</span>, block
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

/**
 * 01 · Enrol. A folder picker, then a determinate per-frame progress grid.
 *
 * The picker browses the *server's* filesystem rather than the browser's. A
 * browser cannot hand a server a path -- `webkitdirectory` gives file
 * contents -- so a folder chooser in the page would mean uploading forty
 * 24-megapixel RAWs, well over a gigabyte, to a service reading the same
 * disk. The console runs on the photographer's machine; it can just look.
 *
 * The frame count beside each folder is the point. Gate A wants 40-50 frames
 * and a picker that does not say which folders have them makes the operator
 * guess at the one number that decides whether K is any good.
 */
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

  /**
   * The operating system's own dialog rather than a directory tree drawn in
   * the browser.
   *
   * The tree was a server-side file browser, which meant the console could
   * only enrol from volumes the API process could see, and the operator had
   * to navigate a machine's filesystem through a list of folder names. A
   * photographer already knows where their frames are and their own file
   * dialog already knows how to get there -- with previews, search, and every
   * shortcut they have set up.
   *
   * The cost is honest: the frames are uploaded rather than read in place,
   * and forty RAW frames is roughly half a gigabyte. It is localhost, so this
   * is memory bandwidth and not network, and `/enrol` still takes a folder
   * path for scripts and the offline run.
   */
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

    // Gate A asks for 40-50. Fewer still enrols -- the estimator's variance
    // falls as 1/d, it does not have a cliff -- so this is a caution and not
    // a refusal.
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

    // Said before anything else, and synchronously. Uploading forty RAW
    // frames takes long enough that a screen which waits for the first
    // server event reads as a hang -- the operator has clicked and been
    // shown nothing, which is the moment they click again.
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
          // The upload is done and the estimator has the frames; the per-frame
          // grid takes over from the byte counter.
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
          // Determinate, because the length is known and a spinner over a
          // half-gigabyte upload tells the operator nothing about whether to
          // wait or intervene.
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

/**
 * 02 · Register. This screen **writes**, and it is the only one that does.
 *
 * An earlier version of this screen called `/verify` like every other screen,
 * which scored the photograph and registered nothing -- so a genuine frame
 * came back `fingerprint-only`, correctly, and looked like a failure. The
 * distinction is the whole product: verifying asks what the chain already
 * says, registering is what puts it there.
 */
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

  // Step 2a, and the step this console never had. Without it a wiped registry
  // left no way to put the body back, and `registerImage` reverted
  // `unknown body` with nothing on screen offering the fix.
  void drawBodyStep(host, ledger as HTMLElement);

  // Multi-select is the bulk path: one file registers an ImageRecord, many
  // commit one session root. The contract has both because they answer
  // different questions -- see `/register-session`.
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
      await showImage(left.querySelector(".slot")!, file);

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

      ledger.innerHTML = `<ol class="ledger">
        <li>scoring against <b>${escape(bodyName)}</b></li>
        <li class="pulse">signing and broadcasting</li></ol>`;

      try {
        const receipt = await api.registerImage(file, bodyName);
        ledger.innerHTML = `<ol class="ledger">
          <li>scored — PCE ${Number(receipt.pce).toLocaleString()}</li>
          <li>signed by the body's owner</li>
          <li>included in block ${escape(receipt.blockNumber)}</li>
        </ol>
        <p class="mono txlink"><a href="${escape(receipt.explorerUrl)}" target="_blank"
           rel="noreferrer">view transaction ↗</a></p>
        ${referenceLinks(receipt.links)}`;

        // Read it back the way a verifier would, rather than trusting the
        // receipt. If the chain does not agree, the demo should show that.
        await scored(host, file);
      } catch (error) {
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
      await showImage(left.querySelector(".slot")!, file);
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
      await showImage(orig.querySelector(".slot")!, file);
      const mid = host.querySelector(".mid")!;
      mid.innerHTML = `<ol class="ledger">
        <li>strip metadata</li><li>resize to 1800px</li><li>re-encode q95</li>
        <li class="pulse">re-score</li></ol>`;
      try {
        const degraded = await api.degrade(file, 1800, 95);
        const copy = host.querySelector(".copy")!;
        copy.innerHTML = `<div class="slot filled"></div>`;
        await showImage(copy.querySelector(".slot")!, degraded, true);
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
      await showImage(left.querySelector(".slot")!, file);
      await scored(host, file);
    }),
  );
};

/**
 * 06 · Archive. What this machine has registered, and what it scored.
 *
 * The chain holds a pixel hash and nothing else, which is right and no use to
 * a photographer: given `0x2224a686…` there is no way to know that was
 * `IMG_0230.CR3`. This screen is the other half of that, and it is local by
 * construction — file paths and captions never go near the network.
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
                    ? // Registered, so the transaction that put it there is the
                      // precise place to check -- better than the contract tab,
                      // which would need the hash pasted back in.
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

      // Captions save on blur rather than behind a button: a photographer
      // labelling an archive types in one field after another, and a save
      // button per row is a click per photograph.
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
  { id: "confidential", label: "07 CONFIDENTIAL", render: confidential },
];

export type { VerifyResult };
