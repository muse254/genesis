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

import { api, type Check, type State, type VerifyResult } from "./api";
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

async function scored(
  host: HTMLElement,
  file: File,
  compare?: { pce: number; label: string },
) {
  host.querySelector(".result-area")!.innerHTML =
    `<p class="working pulse mono">scoring — PRNU on a 24-megapixel frame takes seconds</p>`;
  const started = Date.now();
  const timer = setInterval(() => {
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    const note = host.querySelector(".working");
    if (note) note.textContent = `scoring · ${elapsed}s elapsed · ~9s typical`;
  }, 100);

  try {
    const result = await api.verify(file);
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

/** 00 · Pre-flight. The go/no-go gate, checked before recording starts. */
export const preflight: Render = (host) => {
  host.innerHTML = `
    <h1 class="title">Pre-flight</h1>
    <p class="lede">Every one of these can fail on camera. Checked now, not during.
       Press <b>P</b> to re-run.</p>
    <div class="preflight"><div class="table">loading…</div><div class="gate"></div></div>`;

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
        <div class="browser"><p class="mono">loading…</p></div>
      </div>
      <div class="right"><div class="grid"></div><div class="enrol-side"></div></div>
    </div>`;

  const browser = host.querySelector(".browser")!;
  const grid = host.querySelector(".grid")!;
  const side = host.querySelector(".enrol-side")!;

  const draw = async (path?: string) => {
    browser.innerHTML = `<p class="mono">loading…</p>`;
    let listing: Awaited<ReturnType<typeof api.browse>>;
    try {
      listing = await api.browse(path);
    } catch (error) {
      browser.innerHTML = "";
      browser.append(failure("CANNOT BROWSE", (error as Error).message,
                             "Set GENESIS_BROWSE_ROOT if the archive is on another volume."));
      return;
    }

    const rows = listing.entries
      .map(
        (entry) => `
        <li>
          <button data-path="${escape(entry.path)}">${escape(entry.name)}</button>
          <span class="count ${entry.frames > 0 ? "has" : ""}">${
            entry.frames < 0 ? "—" : `${entry.frames} raw`
          }</span>
        </li>`,
      )
      .join("");

    browser.innerHTML = `
      <p class="here mono">${escape(listing.path)}</p>
      ${listing.parent ? `<button class="up" data-path="${escape(listing.parent)}">↑ up</button>` : ""}
      <ul class="folders">${rows || `<li class="empty">no subfolders</li>`}</ul>
      <div class="chosen">
        <span class="mono">${listing.frames} RAW frames here</span>
        ${
          listing.frames > 0
            ? `<form class="enrol-form">
                 <input name="name" placeholder="body name, e.g. r10" required />
                 <button>Enrol this folder</button>
               </form>
               ${listing.frames < 40 ? `<p class="warn">Gate A asks for 40–50.</p>` : ""}`
            : `<p class="warn">Pick a folder that holds the frames.</p>`
        }
      </div>`;

    browser.querySelectorAll("button[data-path]").forEach((button) =>
      button.addEventListener("click", () => draw((button as HTMLElement).dataset.path)),
    );

    browser.querySelector("form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const name = String(new FormData(event.target as HTMLFormElement).get("name"));
      run(listing.path, name);
    });
  };

  const run = (folder: string, name: string) => {
    let total = 0;
    api
      .enrol(folder, name, (e) => {
        if (e.event === "start") {
          total = Number(e.frames);
          grid.innerHTML = Array.from({ length: total }, () => `<i class="cell"></i>`).join("");
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
              <p class="note">The fingerprint itself stays on this machine;
                 only this commitment goes on chain.</p>
            </div>`;
        }
      })
      .catch((error) =>
        side.append(failure("ENROLMENT FAILED", error.message, "No fingerprint was written.")),
      );
  };

  draw();
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
         rel="noreferrer">view transaction ↗</a></p>`;
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
           rel="noreferrer">view transaction ↗</a></p>`;

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
                <td class="mono">${escape(String(row.image_hash ?? "").slice(0, 14))}…</td>
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
];

export type { VerifyResult };
