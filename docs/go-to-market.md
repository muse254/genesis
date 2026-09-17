# Go-to-market

Written 17 September 2026 for the Colosseum submission. What is measured is
labelled as measured; what is a hypothesis is labelled as one. `docs/claims.md`
governs every sentence here: Genesis sells attribution and dated records, never
truth, and never "fights fake news".

## The problem people already pay for

Photographers lose money when their work is used without a licence or credited
to someone else, and when they cannot show they had it first. Services that
monitor for misuse and recover licensing fees on a photographer's behalf
already exist; Pixsy is one. The evidence they need most is a dated record that
predates the dispute.

The organisations that buy photographs have the mirror-image problem. A photo
competition has to decide whether an entry is a photograph or a composite. A
licensing library or print marketplace has to know who can grant rights to an
image. An agency that takes work from freelancers has to attribute it
correctly.

The existing fix, signing inside the camera (C2PA), is real and growing: Sony
now ships it to news organisations and broadcasters, video included. But it
lives on a few flagship bodies and only covers pictures taken from now on.
Freelancers and most working photographers shoot on cameras that do not have
it, and their archives predate it.

**Genesis works on the camera the photographer already owns, and on the
archive that already exists.** PRNU for what has been shot; C2PA for what will
be. Not a replacement.

## Who buys, in order

1. **Photo competitions.** They already disqualify entries for undisclosed AI
   or compositing, judge a known set of entrants, and run on a calendar. Short
   sales cycle, and a clear moment of use: entry verification.
2. **Licensing libraries, stock and print marketplaces.** A registration that
   predates a dispute turns directly into recovered fees and fewer takedown
   fights. osoroprints, the founder's print business, is the first integration:
   every print sold carries a Genesis certificate linking to its record.
3. **Agencies that buy from freelancers**, news agencies included. The pitch is
   attribution of contributed work on the contributor's own camera, not
   verification of what a picture shows.

**Not a target:** selling newsrooms a fake-news defence. Genesis cannot say
whether a scene is real, the adversaries there are the strongest there are, and
tying photographs to a camera body can endanger a photojournalist. Where
agencies are customers, registration stays opt-in per photograph and the
camera serial stays hidden unless its owner chooses to reveal it.

## What they pay for (hypotheses, to test in week 3)

| Customer | Pays for | Model |
| --- | --- | --- |
| Photographer | A dispute pack: the record, the reveal of the camera commitment, a report an adjudicator can follow | Per dispute. Registration itself stays free within a quota, with fees sponsored |
| Competition | Verification of every entry against its entrants' registered cameras | Per event or per entry |
| Library / marketplace | Registration at upload and verification through an API | Per call, with a monthly tier |
| Agency | Contributor onboarding and a verification API | Seats plus API |

Photographers pay for a dispute, not for insurance. Businesses pay to not have
disputes.

## Distribution

- **Certificates on physical prints.** Every osoroprints certificate links to
  the public verify page, so each buyer sees the product in use.
- **Photographers first, one community at a time.** Nairobi contacts, then the
  photography communities this came from. Onboarding needs no wallet and no
  crypto: the desktop app holds the key and a relayer pays the fee.
- **Competition organisers**, approached with photographers already enrolled.
- **AI agents.** The MCP server lets an agent check an image's registration
  directly, which is how provenance reaches AI platforms and training-data
  pipelines without a sales call.

## Demand validation

Stated as it stands, not as hoped:

- **Measured:** the method works on a real Canon R10 and survives stripping,
  resizing and re-encoding (`docs/gates.md`), and we published the attacks that
  break the fingerprint alone (`docs/adversarial.md`).
- **In progress (week 3, 1–7 October):** ten enrolled cameras that are not the
  founder's, one written note per onboarding covering what confused them and
  what they would pay for, and the first osoroprints customer through the live
  integration.
- **Not yet:** a paying customer, or a conversation with a competition
  organiser. Both are the next step after week 3, and the submission will
  report whatever week 3 actually produced.

## Why this founder

Osoro runs a print business that needs this, shoots on the camera Genesis was
measured against, and attacked their own system before anyone else could.
