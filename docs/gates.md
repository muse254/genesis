# The two gates

Everything else is worthless if the fingerprint doesn't survive the R10's raw
pipeline. Both experiments are cheap. Both are decisive. **Decide by day 2,
not day 10.**

## Gate A — does K exist on this body?

Shoot 40–50 frames of a defocused white wall.

- **CR3, not C-RAW**
- **Long Exposure NR off** — it is dark-frame subtraction applied to the raw itself
- High ISO NR off
- Base ISO
- Evenly exposed, nothing clipping

```bash
python3 fingerprint/fingerprint.py demo
python3 fingerprint/fingerprint.py pair --crop 1024 ~/flats/*.CR3
python3 fingerprint/fingerprint.py enroll --out r10.npz ~/flats/*.CR3
python3 fingerprint/fingerprint.py test --fingerprint r10.npz ~/shoot/*.CR3
```

**Pass:** held-out own frames well above PCE 50, other cameras near zero, at
least an order of magnitude apart.

**Fail:** the pipeline is eroding the fingerprint. Stop. Report honestly. One
afternoon spent.

### Result

| | |
| --- | --- |
| Date run | |
| Frames | |
| Own-body PCE (held out) | |
| Other-body PCE | |
| Separation | |
| Verdict | |

## Gate B — does it survive the web?

Export one enrolled frame at Flickr dimensions (~1800px, JPEG q80). Test it
against the fingerprint **with crop-and-scale search**.

**Pass:** the retroactive claim is live and demo step 4 works. This is the
strong product.

**Fail:** the tool works only on files the photographer still holds. Still a
real product — an archive claim tool — but step 4 comes out and the pitch
changes.

### Result

| | |
| --- | --- |
| Date run | |
| Export settings | |
| PCE after web round trip | |
| Best scale | |
| Verdict | |
