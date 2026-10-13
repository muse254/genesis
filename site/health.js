// Live status of the deployed dependencies. Checks contract code at the
// address: an RPC and a subgraph answer happily for the wrong registry.
const REGISTRY = "0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB";
const RPC = "https://mainnet.base.org";
const SUBGRAPH = "https://api.studio.thegraph.com/query/1758974/genesis/v1.0.0-base";

function row(name, status, detail) {
  const dotClass = status === "up" ? "up" : status === "down" ? "down" : "unknown";
  return `<div class="health-row">
    <span class="dot ${dotClass}"></span>
    <span class="name">${name}</span>
    <span class="detail">${detail}</span>
  </div>`;
}

async function checkRpc() {
  try {
    const [blockRes, codeRes] = await Promise.all([
      fetch(RPC, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_blockNumber", params: [] }),
      }),
      fetch(RPC, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "eth_getCode", params: [REGISTRY, "latest"] }),
      }),
    ]);
    const [block, code] = await Promise.all([blockRes.json(), codeRes.json()]);
    const blockNumber = parseInt(block.result, 16);
    const hasCode = (code.result ?? "0x").length > 2;
    if (!hasCode) return row("Base registry", "down", `RPC up (block ${blockNumber}) but no contract code at ${REGISTRY}`);
    return row("Base registry", "up", `block ${blockNumber} · <a href="https://basescan.org/address/${REGISTRY}">${REGISTRY.slice(0, 10)}…</a>`);
  } catch (err) {
    return row("Base registry", "down", `RPC unreachable (${err.message})`);
  }
}

async function checkSubgraph() {
  try {
    const res = await fetch(SUBGRAPH, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "{ _meta { block { number } hasIndexingErrors } bodies(first: 1000) { id } images(first: 1000) { id } }" }),
    });
    const payload = await res.json();
    if (payload.errors?.length) return row("Subgraph (The Graph)", "down", payload.errors[0].message);
    const meta = payload.data._meta;
    const bodies = payload.data.bodies.length;
    const images = payload.data.images.length;
    if (meta.hasIndexingErrors) return row("Subgraph (The Graph)", "down", `indexing errors, stalled at block ${meta.block.number}`);
    return row("Subgraph (The Graph)", "up", `synced to block ${meta.block.number} · ${bodies} ${bodies === 1 ? "body" : "bodies"}, ${images} ${images === 1 ? "image" : "images"} indexed`);
  } catch (err) {
    return row("Subgraph (The Graph)", "down", `unreachable (${err.message})`);
  }
}

function checkScoringService() {
  // Not hosted yet, so a known-gap notice rather than a network check.
  return row("Public scoring service", "unknown", "not hosted yet — fingerprint-only verdicts need it, exact/derived matches don't");
}

async function loadHealth() {
  const panel = document.getElementById("health");
  const [rpc, subgraph] = await Promise.all([checkRpc(), checkSubgraph()]);
  panel.innerHTML = rpc + subgraph + checkScoringService();
}

loadHealth();
