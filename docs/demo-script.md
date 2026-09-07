# The demo — target 90 seconds

Everything in this repo is scaffolding for this.

1. **Enrol the R10** from a folder of existing photographs.
2. **Register a photograph** → ERC-7053 `commit()`, ENS name resolves to the body.
3. **Test a photograph from a different camera** → near zero, no match.
4. **The money shot:** take the registered photograph, strip every byte of
   metadata, resize it, re-encode as a web JPEG — and it *still resolves*,
   via the pHash-plus-PRNU branch. An exact-hash scheme cannot do this.
5. **Verify page:** exposed on `r10-4471.cam.osoro.eth`, registered 14:02 UTC.

If step 4 works, the pitch writes itself. If Gate B fails, step 4 comes out
and the pitch becomes an archive-claim tool.

## Recording checklist

- [ ] Clean machine, follow the README from the top
- [ ] Chain state reset, so registration is live on camera
- [ ] ENS subname registered live — no hardcoded values anywhere on this path
- [ ] Terminal font large enough to read at 720p
- [ ] Say "origin, not truth" out loud at least once
