/**
 * Look up an address, no login.
 *
 * Everything here — a body's owner, its commitments, its images — is
 * already public on the subgraph (schema: subgraph/schema.graphql). Gating
 * it behind a wallet signature would only add friction, not privacy, since
 * anyone can already run this same query directly against
 * VITE_SUBGRAPH_URL. "Use my wallet" below is a convenience that fills the
 * input with the connected account; it never asks for a signature and its
 * absence changes nothing about what the form can look up.
 */

interface EthereumProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}
declare global {
  interface Window {
    ethereum?: EthereumProvider;
  }
}

const SUBGRAPH = import.meta.env.VITE_SUBGRAPH_URL as string | undefined;
const EXPLORER = (import.meta.env.VITE_EXPLORER_URL as string | undefined) ?? "https://sepolia.basescan.org";

interface ImageRow {
  id: string;
  imageHash: string;
  perceptualHash: string;
  modificationLevel: number;
  pceScore: string;
  registeredAt: string;
  parent: { id: string } | null;
}

interface BodyRow {
  id: string;
  owner: string;
  bodyCommitment: string;
  fingerprintCommitment: string;
  revoked: boolean;
  registeredAt: string;
  images: ImageRow[];
}

const QUERY = `
  query Owned($owner: Bytes!) {
    bodies(where: { owner: $owner }, orderBy: registeredAt) {
      id owner bodyCommitment fingerprintCommitment revoked registeredAt
      images(orderBy: registeredAt, first: 1000) {
        id imageHash perceptualHash modificationLevel pceScore registeredAt
        parent { id }
      }
    }
  }
`;

function short(hex: string, keep = 10): string {
  return hex.length > keep * 2 ? `${hex.slice(0, keep)}…${hex.slice(-6)}` : hex;
}

function formatDate(unixSeconds: string): string {
  return new Date(Number(unixSeconds) * 1000).toLocaleString();
}

function explorerLink(kind: "address" | "tx", value: string): string {
  return `${EXPLORER}/${kind}/${value}`;
}

async function lookup(owner: string): Promise<BodyRow[]> {
  if (!SUBGRAPH) throw new Error("VITE_SUBGRAPH_URL is not set");
  const response = await fetch(SUBGRAPH, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: QUERY, variables: { owner: owner.toLowerCase() } }),
  });
  if (!response.ok) throw new Error(`subgraph returned ${response.status}`);
  const payload = (await response.json()) as { data?: { bodies?: BodyRow[] }; errors?: { message: string }[] };
  if (payload.errors?.length) throw new Error(payload.errors[0].message);
  return payload.data?.bodies ?? [];
}

function renderBody(body: BodyRow): string {
  const revoked = body.revoked ? " revoked" : "";
  const rows = body.images
    .map(
      (img) => `
      <tr>
        <td class="hash"><a href="${explorerLink("tx", img.id)}">${short(img.imageHash)}</a></td>
        <td>${img.modificationLevel}</td>
        <td>${img.pceScore}</td>
        <td>${img.parent ? short(img.parent.id, 6) : "—"}</td>
        <td>${formatDate(img.registeredAt)}</td>
      </tr>`,
    )
    .join("");

  return `
    <section class="body-card${revoked}">
      <h2>${short(body.id, 12)}${body.revoked ? " · revoked" : ""}</h2>
      <div class="row"><span class="k">Owner</span><span class="v"><a href="${explorerLink("address", body.owner)}">${body.owner}</a></span></div>
      <div class="row"><span class="k">Body commitment</span><span class="v">${short(body.bodyCommitment, 14)}</span></div>
      <div class="row"><span class="k">Registered</span><span class="v">${formatDate(body.registeredAt)}</span></div>
      <div class="row"><span class="k">Images</span><span class="v">${body.images.length}</span></div>
      ${
        body.images.length
          ? `<table class="images">
              <thead><tr><th>Image</th><th>Mod. level</th><th>PCE</th><th>Parent</th><th>Registered</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>`
          : ""
      }
    </section>`;
}

function setStatus(message: string, isError = false): void {
  const el = document.getElementById("status")!;
  el.textContent = message;
  el.classList.toggle("error", isError);
}

async function runLookup(address: string): Promise<void> {
  const results = document.getElementById("results")!;
  results.innerHTML = "";
  if (!/^0x[0-9a-fA-F]{40}$/.test(address)) {
    setStatus("Enter a full 0x… address (40 hex characters).", true);
    return;
  }
  setStatus("Querying the subgraph…");
  try {
    const bodies = await lookup(address);
    if (!bodies.length) {
      setStatus("No bodies registered under this address.");
      return;
    }
    setStatus(`${bodies.length} ${bodies.length === 1 ? "body" : "bodies"} found.`);
    results.innerHTML = bodies.map(renderBody).join("");
  } catch (err) {
    setStatus(`Lookup failed: ${(err as Error).message}`, true);
  }
}

document.getElementById("lookup-form")!.addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("address") as HTMLInputElement;
  void runLookup(input.value.trim());
});

document.getElementById("connect")!.addEventListener("click", async () => {
  if (!window.ethereum) {
    setStatus("No wallet extension found.", true);
    return;
  }
  try {
    const accounts = (await window.ethereum.request({ method: "eth_requestAccounts" })) as string[];
    if (accounts[0]) {
      (document.getElementById("address") as HTMLInputElement).value = accounts[0];
      void runLookup(accounts[0]);
    }
  } catch (err) {
    setStatus(`Wallet connection failed: ${(err as Error).message}`, true);
  }
});

// Deep-linkable: /dashboard/?owner=0x…
const preset = new URLSearchParams(location.search).get("owner");
if (preset) {
  (document.getElementById("address") as HTMLInputElement).value = preset;
  void runLookup(preset);
}
