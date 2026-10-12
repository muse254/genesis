# Demo video script, about 2 minutes

Recorded 12 October 2026 against the Base mainnet registry
`0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB`. One photograph is registered
live on camera. The claim the whole video makes: **a copy that has been
stripped, resized and re-encoded still traces back to its owner's record,
and a forger cannot write a record to someone else's camera.**

## Before you record

- [ ] Console API running: `uvicorn console.app:app --host 127.0.0.1 --port 8100`,
      with `.env` loaded.
- [ ] Console UI running: `cd console-ui && npx vite --port 5173`. Open
      <http://127.0.0.1:5173/> and check the R10 shows as registered.
- [ ] Tabs open: the console, the verify page
      (<https://muse254.github.io/genesis/verify/>), and the registry on
      Basescan (<https://basescan.org/address/0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB>).
- [ ] Finder open at `~/Desktop/genesis-demo/`, with these files:
  - `1-register-live.jpg`, the original R10 photo (`chess.jpg`, 6000×4000,
    with EXIF). **Not registered yet.**
  - `2-web-copy.jpg`, the same photo at 1200×800, JPEG quality 70, no EXIF.
  - `3-forged.jpg`, an image no camera took.
  - `try-to-forge.sh`, the read-only forgery attempt.
- [ ] A terminal at a large font, sitting in `~/Desktop/genesis-demo/`.
- [ ] Notifications off, and the browser zoomed so the text reads at 720p.

**Registering takes one take.** After Scene 2, `1-register-live.jpg` is on
mainnet permanently, and a second attempt will say "already registered". If
a later scene goes wrong, re-record only that scene. For a full re-take, use
another unregistered OsoroPrints photo, such as `errand.jpg` (PCE 41,251)
or `lone.jpg` (PCE 6,941). Rebuild its web copy the same way.

## Scenes

### 1. The problem (0:00–0:12)

*Show: the verify page, empty.*

> "Everyone is trying to prove a photo isn't AI. That's proving a negative.
> Genesis records a positive instead: this photographer registered this
> photo, from this camera, at this time, on a public record."

### 2. Register a photo live (0:12–0:40)

*Show: the console at :5173. Point out that the R10 is registered, then open
**Register photos**, drop `1-register-live.jpg` and confirm.*

> "This is my Canon R10. Its sensor has a fingerprint, measured from RAW
> files I already had, and the camera is registered on Base. I drop in a
> photo. It's scored against the camera's fingerprint first, and here it
> matches at a PCE in the thousands, against a threshold of 100. Only then
> is it registered."

*Show: the result with its transaction link. Click it to show Basescan.*

> "That's the record, on Base mainnet. The photo itself never left my
> machine. Only its hashes are on chain."

### 3. Anyone can check it (0:40–0:55)

*Show: the verify page. Drop `1-register-live.jpg`.*

> "Anyone can check it, in a browser. No account, no wallet. The page
> hashes the photo locally and asks the chain."

*Hold on the verdict: **Registered by the body's owner**, with the time.*

### 4. The copy that already left (0:55–1:25): the money shot

*Show: Finder's Get Info on both files side by side. 6000×4000 against
1200×800, and the size drops from about 36 MB to about 140 KB. Then drop
`2-web-copy.jpg` on the verify page.*

> "But photos don't stay as originals. This is the version that gets posted:
> resized, re-compressed, every byte of metadata gone. An exact-hash scheme
> loses it here."

*Hold on the verdict: **Descends from a registered photograph**.*

> "Genesis still finds it. A perceptual hash finds the candidate, and the
> chain confirms the record. This copy traces back to the original, to my
> camera and to me."

### 5. A forger (1:25–1:50)

*Show: the terminal. Run `./try-to-forge.sh`.*

> "Now the attack. We published our own attacks: anyone holding one RAW
> file can plant a camera's fingerprint in an image it never took, so the
> fingerprint score alone isn't proof. That's why the score never carries
> the claim on its own. Here a forger tries to register this image to my
> camera, claiming a perfect score."

*Hold on: **REFUSED: not the body owner**.*

> "The registry refuses. Only the key that owns this camera can register
> to it. The score is evidence; the owner's registration is the claim."

### 6. Close (1:50–2:00)

*Show: the registry on Basescan.*

> "Genesis is live on Base mainnet today. Origin, not truth: it says who
> registered a photo, from which camera, and when. It never says the scene
> was real."

## What not to say

These come from `docs/claims.md`.

- Never "authentic", "AI-free", "verified real" or "proven".
- Never imply that "No record" means fake.
- The PCE number is strength of evidence, not a probability.
- Scene 5 is a simulation (`cast call`). Nothing is sent. Say "the registry
  refuses", not "we blocked a real attack".
