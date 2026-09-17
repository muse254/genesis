# Colosseum — Crypto World's Fair

**Deadline: Sunday 12 October 2026.** Written 17 September. 25 days.

Hackathon execution brief. `BUILD.md` is still what the project *is*;
`docs/security.md` and `docs/adversarial.md` are still what it defends and
what it does not. This document only says how the next 25 days are spent.

**It deliberately specifies no new forensics.** `docs/adversarial.md`
§"Proposals, ranked" already scopes that work, with measurements behind it.
Where this document and that one differ on technical priority, that one wins.

---

## 1. What the judging actually rewards

Colosseum score founder + market fit, insight, product + execution, market
size, founder communication, viability, and **traction** — and tell entrants
to treat the submission as a pitch to their venture fund.

Three consequences:

1. **Nobody is scoring the stack.** All submissions compete in one pool
   regardless of chain. There is an Ethereum track, a Base track and an
   Arbitrum track. Do not re-platform to chase one.
2. **Traction is the only empty column.** Real enrolled bodies belonging to
   people who are not the founder outrank any feature.
3. **`docs/adversarial.md` is the insight criterion, already earned.** Four
   measured attacks, three numbers that failed to reproduce and were
   corrected, a negative result on [B18] reported rather than buried. Almost
   no submission in this pool will have anything comparable. It should be
   linked from the README and referenced in the pitch, not left for a judge
   to find.

**The highest-value outcome of these 25 days: strangers have enrolled
cameras, and the registry is on mainnet.**

---

## 2. Decisions needed before week 1

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Deploy target | **Base mainnet.** `BUILD.md` §8 already concluded Base once ENS stops pinning us to Sepolia. Real mainnet is affordable there; on L1 it is not. |
| D2 | Does ENSv2 survive this round? | Note that `security.md`'s body commitment lives in the **resolver records**. Dropping ENS means rehoming it. That is a real cost and D2 is not free — decide deliberately. |
| D3 | Hours/day, alongside osoroprints and the job search | Plan assumes ~3h/day. |

Budget: Base gas, one host for the scorer, one domain. Under $100.

**Decided 17 September:**

- **D1 — Base mainnet.**
- **D2 — ENS is dropped this round; the body commitment moves into the
  Registry.** A mainnet deploy is a fresh contract anyway, so `security.md`'s
  reason for using the resolver ("adding a field means redeploying and
  abandoning the live registration") no longer applies. `identity/` was
  removed from the branch on 17 September and stays at the
  `ethonline-submission` tag.
- **D3 — ~3h/day.** The plan stands as written.

---

## 3. Non-goals — binding

- **No Solana rewrite.** Ethereum, Base and Arbitrum tracks all exist.
- **No token.** Contradicts the thesis; puts us in `BUILD.md` §2's graveyard.
- **No zero-knowledge proofs.** Not a 25-day problem.
- **No Chainlink CRE.** Always first to cut. Stays cut.
- **No journalism positioning.** Individual photographers, per the decision
  already taken.
- **No keyed transform of K.** `adversarial.md` already proved it cannot work.

**Never cut:** the fingerprint core, the verify page, or week 3.

---

## 4. Week 1 — 17–23 Sept · Go live

Nothing new is built. What works goes into production.

| Task | Done when |
| --- | --- |
| Deploy the registry to mainnet | Verified on the explorer; address pinned; tx linked |
| Host the scoring service | HTTPS on a real domain, health check green, survives reboot |
| Verify page public | Upload an image, get a verdict, both Flow C branches live |
| Register the R10 for real | Body enrolled on mainnet, 20+ photographs registered and resolvable publicly |
| README for a stranger | Verify an image in 60 seconds without opening `BUILD.md`. Link `adversarial.md` prominently |

**Done when you can send someone a link and they can check a photo.** If week 1
slips everything slips. Protect it.

---

## 5. Week 2 — 24–30 Sept · Two things, both already scoped elsewhere

1. **Whatever `adversarial.md` §"Proposals, ranked" says is next.** Tier 1
   item 2, the hot-pixel and defect map, is the unbuilt one and it is cheap.
   Do not re-specify it here and do not rebuild items 1 and 3 — they shipped
   on 8 September in `fingerprint/consistency.py`.
2. **The MCP server made real.** The submission leads on agents: provenance
   infrastructure an AI agent can query directly. `mcp/` has to work, not be
   sketched. This is the AI story and it is already in `BUILD.md` §7.

---

## 6. Week 3 — 1–7 Oct · Traction

The empty column. Non-negotiable.

| Task | Done when |
| --- | --- |
| osoroprints integration | Every print sold carries a Genesis certificate linking to its record. One push: live integration, first customer, demo that shows rather than tells |
| Onboard real photographers | **10 enrolled bodies that are not yours.** Nairobi contacts first, then the photography communities this came from |
| Write down what they say | Every onboarding produces a note — what confused them, what they'd pay for. This is the founder-market-fit evidence |

Ten strangers with enrolled cameras beats any feature on the cut list.

---

## 7. Week 4 — 8–12 Oct · The pitch

A week, not a night.

- **Demo.** Gate B: register a photograph, strip metadata, resize, re-encode
  as web JPEG — still resolves. Then show a forgery being caught.
- **Insight, one sentence.** The photo world is verifying a negative. We
  verify the positive, and it works on images that already left.
- **Lead with the adversarial work.** "We attacked our own system, published
  the numbers, corrected three of them when they failed to reproduce, and
  reported a defence that did not work." That is the insight criterion and
  nobody else will do it.
- **The Nikon paragraph** — currently in no document here. Nikon shipped free
  C2PA on the Z6III in August 2025, suspended the service that September after
  Multiple Exposure mode produced validly signed composites, and revoked every
  certificate it had ever issued. Manufacturer attestation: breakable, and
  revocable by someone who is not the photographer. A sensor fingerprint is
  neither.
- **The paywall map.** Sony charges to sign and again to verify. Canon ships
  it on two flagships. No body under ~$2,000 has it. We work on the camera the
  photographer already owns.
- **Positioning, per `adversarial.md`:** PRNU for the archive that already
  exists, C2PA for what is shot from now on. Not a replacement.
- **Market.** Photo competitions first. Then stock and licensing, AI
  training-data provenance, print marketplaces. Photographers pay for a
  dispute, not for insurance.
- **Claims discipline holds.** `docs/claims.md` governs the pitch too.

---

## 8. Cut order

Cut from the bottom.

1. Anything in `adversarial.md` tier 2 or 3
2. Hot-pixel map
3. MCP polish beyond working

**Never cut:** mainnet deploy, verify page, fingerprint core, week 3.

---

## 9. Open, raise rather than guess

- Confirm the event: the site shows Crypto World's Fair 14 Sept – 12 Oct; the
  blog lists a Fall hackathon 28 Sept – 2 Nov. Possibly the same thing renamed.
- Prior-work disclosure is mandatory; judging counts only in-window work. Last
  commit before the window was 13 September, so `git log --since=2026-09-14`
  is the disclosure. Prepare it honestly and early.
- **No LICENSE in the repo.** Open-source status is scored. Decide before
  submission.
