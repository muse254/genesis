# Platform plan: proving a photo is not AI

Written 6 October 2026. Goal: a live platform that a platform, contest or
archive can use to answer "did a real camera capture this?", with Osoro
marketing and the build done in parallel.

## 1. What platforms do today

| Method | Who uses it | Proves | Weakness |
| --- | --- | --- | --- |
| C2PA signed manifests (camera or phone signs at capture) | Leica, Sony and Canon (newsroom tier), Pixel, Samsung; read by Adobe, LinkedIn, Cloudflare | This device signed these pixels at time T | Few cameras sign; metadata is stripped on upload; the maker's signing key is trusted, and Nikon's revocation showed it can fail |
| Invisible watermarks and fingerprints on generated images (SynthID, Meta, OpenAI) | Google, Meta, OpenAI | This came from *that vendor's* model | Says nothing about images from other or open models; absence proves nothing |
| AI-image classifiers | Hive, Reality Defender, Sensity, Illuminarty | A probability | Overfit to known generators; platforms treat it as a hint, not a verdict |
| Contest RAW and process checks | World Press Photo, Sony Awards, Siena | The finalist can produce the sensor file | Manual, costly, and defeated by a determined entrant |
| Reverse-image search and first-seen dating | TinEye, Google Lens, newsroom verification desks | Earliest known appearance | Proves "seen before", not "captured" |
| Platform self-labels and uploader attestation | Meta, YouTube, TikTok, Adobe Stock | The uploader says so | Honour system |

The gap Genesis fills: **cryptographically anchored, maker-independent
evidence that a given file was registered by a known camera owner at a known
time**, which works on cameras that do not sign and on archives that cannot be
re-shot.

## 2. What we can and cannot claim

Say: "Registered capture. Registered on chain at T by the owner of body B,
whose sensor fingerprint matched at registration."

Do **not** say: "Proven not AI." The fingerprint can be planted from one RAW
(`docs/adversarial.md`), so a match is never proof. What the platform proves is
priority and accountability: who registered it first, who is on the hook if it
is false. Marketing copy has to hold that line (FTC v. Workado is the
precedent for unsubstantiated accuracy claims). Detector scores add doubt and
never confidence.

## 3. Product: the smallest thing that is live and sellable

Buyers are institutions (contests, licensors/archives, agencies), so the first
product is a **verification service for organisations**, not a consumer app.

1. **Public verify page** (exists in `core/` and `verify/`): drop a file, get
   `registered` / `derived` / `fingerprint-only` / `no-record`. Add a shareable
   result URL and a C2PA-compatible output.
2. **Organisation console** (`dashboard/`): accounts, SSO later, a list of
   contributors enrolled under the org, registration history, and a
   verification log exportable as PDF/CSV.
3. **Intake API and SDK**: `POST /verify`, `POST /register`, webhooks. The
   contest or archive calls this from its own submission flow.
4. **Contributor enrolment**: browser/desktop capture-and-enrol (LibRaw WASM is
   done). Hosted, custodial signing so the contributor needs no wallet.

## 4. Fixes before anything goes live

These come from the audit of the current repo and are blocking for an honest
launch.

| # | Item | Where | Why |
| --- | --- | --- | --- |
| F1 | Earliest-registration check across near-duplicates | `core/src/verify.ts` | An exact or perceptual hit returns `registered` without comparing `registeredAt`. A later laundered copy can win. |
| F2 | Copy: stop saying "this camera body" on a hit | verify page | A hit means "registered by the owner of B", not "captured by B". |
| F3 | K-against-K duplicate check at enrolment | enrolment service, off-chain first | `registerBody` accepts any 32 bytes, so one camera can be enrolled under two estimates. |
| F4 | Replace the subgraph scan | `core/src/chain.ts` | `images(first: 1000)` plus client-side Hamming does not scale and gives false matches. Use a server-side nearest-neighbour index. |
| F5 | Key custody | `console/registry.py` | A private key is passed through `argv` to `cast`. Move to a KMS or HSM signer before any hosted use. |
| F6 | Mainnet readiness | `docs/mainnet-deploy.md` | One-way deploy. Keep `testMode`/`resetAll` out of the mainnet build; finish the checklist first. |
| F7 | Claims wording | `docs/claims.md`, site | Align every public sentence with section 2. |

Do F1, F2 and F7 first: small, and they decide what the product says.

## 5. Ship order

| Phase | Weeks | Deliverable | Exit test |
| --- | --- | --- | --- |
| 0. Honest base | 1 | F1, F2, F7; public verify page on a domain | A laundered second registration no longer outranks the first |
| 1. Pilot-ready | 2–5 | Org accounts, intake API, hosted signer (F5), F3 dedupe, result URLs, audit log | One partner can submit 100 images end to end without us touching it |
| 2. Mainnet | 5–7 | F4, F6, deploy, monitoring, status page | 30 days of uptime and a clean rehearsal restore |
| 3. Enterprise basics | 6–10 | SSO, DPA, SOC 2 Type I started, terms with arbitration clause | A buyer's security questionnaire can be answered |
| 4. Accountability layer | later | Witnessed enrolment, KYC with escrow, bond | Only once a buyer asks for it |

KYC, witnesses, bonds and liability (the forger-with-the-camera design) are
real but expensive and legally heavy. Do not build them before a customer
wants the guarantee they provide. Start with terms that name the owner as
liable, and an enrolment record that can be audited.

## 6. Go-live checklist

- [ ] Domain, TLS, status page, error monitoring
- [ ] Hosted signer on KMS, no keys in env or argv
- [ ] Mainnet contract deployed from a clean build, address published, source verified
- [ ] Privacy notice and DPA template (images stay on the device by default; only hashes leave)
- [ ] Terms of service: English law, London arbitration, owner liability for false registration, third-party reliance
- [ ] Public claims page matching section 2
- [ ] Backup and restore tested for the index and enrolment database
- [ ] Rate limits and abuse controls on the verify and register endpoints

## 7. The marketing side (for Osoro)

Per the market research: contests, archives/AI-data licensors and agencies are
the buyers. Ask each the same question: "Would you pay more, or accept more
submissions, if every photo carried a dated registration from a known camera?"
Aim for ten conversations and one paid pilot or letter of intent in 30 days.
Test the cheaper product alongside it (dated, accountable registration with no
fingerprint); if that is what they want, the fingerprint is a feature.

Lead with: archives cannot be signed after the fact; camera-maker signatures
sit outside C2PA's official trust list; contests keep being fooled. Do not
quote revenue forecasts.

## 8. Open decisions

1. Hosted custodial signing vs. contributor-held wallet (recommend custodial).
2. Which chain to launch on (Base, as built).
3. Whether the first pilot is a contest or a licensor.
4. Whether the colosseum-branch rule still applies before 12 Oct 2026; nothing
   here is committed yet.
