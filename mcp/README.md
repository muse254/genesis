# Genesis MCP server

Lets an AI agent ask the Genesis registry about a photograph. Point it at an
image file, or give it a hash, and it says whether that image is registered,
by which camera body's owner, and when.

It reads only. No tool registers anything. Registering needs the camera's
fingerprint, and the fingerprint never leaves the photographer's machine.

| tool | takes | answers |
|---|---|---|
| `verify_image_file` | path to a JPEG, PNG or TIFF on this machine | hashes the file locally, exactly as the [verify page](../verify/) does, then looks it up: exact pixels first, then the nearest registered image by perceptual hash |
| `verify_image` | pixel SHA-256 (`0x…`) | the registration for that hash, if there is one |
| `lookup_body` | body id, or camera commitment | the body's record and whether it has been revoked |
| `image_lineage` | pixel SHA-256 | the registered original and every registered derivative |

The answers report where an image came from. They never say an image is
authentic. A match means someone registered these pixels under a body they
own. It does not mean the scene was real (see `docs/claims.md`).
`verify_image_file` never sends the photo anywhere. Only its pixel hash goes
out, plus one query that fetches the registered perceptual hashes so they
can be compared locally.

## Prerequisites

- **Node.js 22** or newer.
- **For `verify_image_file` only:** core/'s two WASM modules, built once.
  They are the verify page's decoders and hashers, and they are not
  committed. Building them needs:
  - Rust with the `wasm32-unknown-unknown` target:
    `rustup target add wasm32-unknown-unknown`
  - [`wasm-pack`](https://rustwasm.github.io/wasm-pack/installer/)
  - [Emscripten](https://emscripten.org/docs/getting_started/downloads.html)
    (`emcc` on your PATH) and `cmake`, to build libjpeg-turbo.

  Without them the server still builds and runs, and the other three tools
  work. `verify_image_file` then replies with how to build the modules.

## Build

From a clone of the repository:

```sh
# 1. The WASM (only for verify_image_file; takes a few minutes the first time)
cd core
npm ci
npm run wasm

# 2. The server
cd ../mcp
npm ci
npm run build     # tsc, then copies core's hashing and WASM into dist/core
npm test
```

`npm run build` prints `core hashing bundled into dist/core` when it found
the WASM. If it prints `note: core's WASM is not built`, do step 1, then run
`npm run build` again. To make a missing WASM fail the build, run
`GENESIS_REQUIRE_CORE=1 npm run build`.

The hashing is core's code, not a copy of it. The build strips the types
from `core/src/hashes.ts` and `core/src/chain.ts` and puts them next to the
WASM in `dist/core/`. So the server gets the same digests as the verify
page, the desktop app and `ingest/hashing.py`. `npm test` checks this on
every committed hash fixture, JPEG included.

## Configure

| variable | default | meaning |
|---|---|---|
| `GENESIS_SUBGRAPH_URL` | — | Read this subgraph. Takes precedence over `GENESIS_CHAIN` |
| `GENESIS_CHAIN` | `base` | Read the subgraph published for this chain: `base` (production), `base-sepolia` (the rehearsal registry), `sepolia` (the older ETHOnline registry), or `anvil` (a local graph-node at `127.0.0.1:8000`) |

With neither set, the server reads the Base mainnet registry 1.0.0, the one
the verify page uses:
`https://api.studio.thegraph.com/query/1758974/genesis/v1.0.0-base`.

The Studio query URL above has a rate limit. It is fine for an agent
checking a few photos. For heavy use, publish the subgraph to The Graph's
network and point `GENESIS_SUBGRAPH_URL` at a gateway URL with your API key.

## Add it to an agent

In each example, replace `/abs/path/to/certify-the-camera` with the absolute
path of your clone.

### Claude Code

```sh
claude mcp add genesis -- node /abs/path/to/certify-the-camera/mcp/dist/server.js
```

To read a different registry:

```sh
claude mcp add genesis -e GENESIS_CHAIN=base -- node /abs/path/to/certify-the-camera/mcp/dist/server.js
```

Check it with `claude mcp list`, or with `/mcp` inside a session.

### Claude Desktop

Open *Settings → Developer → Edit Config*. This opens
`claude_desktop_config.json` (on macOS it is in
`~/Library/Application Support/Claude/`). Add:

```json
{
  "mcpServers": {
    "genesis": {
      "command": "node",
      "args": ["/abs/path/to/certify-the-camera/mcp/dist/server.js"],
      "env": { "GENESIS_CHAIN": "base" }
    }
  }
}
```

Restart Claude Desktop. The four tools appear under the tools icon. If
`node` is not found, put the full path to it in `command` (`which node`).

### Any other MCP client

The server speaks MCP over stdio: `node mcp/dist/server.js`.

## Example prompts

- "Is `~/Pictures/harbour.jpg` registered with Genesis? Who registered it,
  and when?"
- "Check every JPEG in `~/Desktop/submissions` against the Genesis registry
  and tell me which ones have a record."
- "Genesis says image `0xf01134286dfebac904dcb5b82339bbfdbed7b0b00ed9cc27dcd9da125aa9936e`
  is registered. Which body registered it, and is that body revoked?"
- "Show me the edit lineage of
  `0x0565680eb95abf636d32f9085b814603053623858bb899b5370a2a906cd4b2d5`."

Those two hashes are real registrations on Base Sepolia.

Use absolute paths, or paths starting with `~/`. A relative path is resolved
against the directory the client started the server in, which is rarely the
one you expect.

## What the answers mean

- **A record.** These exact pixels were registered by the owner of the body
  shown, at the time shown, with the PCE score shown. The answer states what
  that does and does not establish.
- **"No registration for these exact pixels", then a nearest image.** The
  file differs from every registered image by at least one pixel. One
  registered image has a perceptual hash within 10 of 64 bits of it, which is
  the tolerance the verify page uses. This is a lead: the file may be a
  re-encoded, resized or edited copy of that image, or an unrelated image
  that hashes close to it. The record shown belongs to the registered
  original, not to this file.
- **"No record".** Nothing is registered under this hash. That does not mean
  the image is fake. Most photographs are not registered.
- **RAW files are refused.** A registration hashes the developed image, and
  developing a RAW the way enrolment does is the desktop app's job. Export a
  JPEG, PNG or TIFF and check that.

These answers come from The Graph's index. The verify page also reads the
registry contract before it says "registered". Treat a record from this
server as a strong pointer, and confirm it on the verify page or on a block
explorer when it matters.

## Development

```sh
npm run build && npm test
```

- `src/queries.test.ts` tests the wording an agent repeats: never "verified"
  or "authentic", and a missing record never reads as "fake".
- `src/image.test.ts` checks the hash parity against core's fixtures
  (`rust/genesis-prnu/tests/fixtures/hashing`), and tests `verify_image_file`
  against a stubbed subgraph: an exact hit, a perceptual lead, and no record.
  These tests are skipped, and say why, when core's WASM was not built. CI's
  `mcp` job does not build the WASM, so there they are skipped.
