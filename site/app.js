// Reads assets off the latest published GitHub release rather than hardcoding
// filenames or versions here -- desktop.yml names its assets after
// tauri.conf.json's productName + version, and this page would otherwise go
// stale every time either changes. Drafts are deliberately invisible to
// `/releases/latest` (desktop.yml: "Draft on purpose: a person publishes
// it."), so an empty result here means nobody has published one yet, not
// that the request failed.
const REPO = "muse254/genesis";

const PLATFORMS = [
  { key: "macos", label: "macOS (Apple Silicon)", match: (name) => name.endsWith(".dmg") },
  { key: "windows", label: "Windows", match: (name) => name.endsWith(".msi") || name.endsWith("-setup.exe") },
  { key: "linux", label: "Linux (AppImage)", match: (name) => name.endsWith(".appimage") },
  { key: "linux-deb", label: "Linux (.deb)", match: (name) => name.endsWith(".deb") },
];

function detectPlatform() {
  const ua = navigator.userAgent;
  if (/Mac/.test(ua)) return "macos";
  if (/Win/.test(ua)) return "windows";
  if (/Linux/.test(ua)) return "linux";
  return null;
}

function formatSize(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadRelease() {
  const panel = document.getElementById("downloads");
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (res.status === 404) {
      panel.innerHTML = `<p class="notice">No build has been published yet. Check
        <a href="https://github.com/${REPO}/releases">the releases page</a> directly,
        or watch <a href="https://github.com/${REPO}/actions/workflows/desktop.yml">the
        build workflow</a>.</p>`;
      return;
    }
    if (!res.ok) throw new Error(`GitHub API returned ${res.status}`);
    const release = await res.json();

    const preferred = detectPlatform();
    const buttons = [];
    for (const platform of PLATFORMS) {
      const asset = release.assets.find((a) => platform.match(a.name.toLowerCase()));
      if (!asset) continue;
      const isPrimary = platform.key === preferred || (platform.key === "linux" && preferred === "linux");
      buttons.push(`
        <a class="download-btn" data-primary="${isPrimary}" href="${asset.browser_download_url}">
          <span class="platform">${platform.label}</span>
          <span class="filesize">${formatSize(asset.size)}</span>
        </a>`);
    }

    panel.innerHTML = `
      <span class="label">Download</span>
      <div class="platform-picks">${buttons.join("")}</div>
      <p class="version">${release.tag_name} · unsigned builds -- macOS: right-click and choose
        Open the first time. Windows: choose "More info" then "Run anyway" on the SmartScreen
        prompt.</p>
      <p class="fallback">All installers, checksums and release notes:
        <a href="${release.html_url}">${release.html_url}</a></p>`;
  } catch (err) {
    panel.innerHTML = `<p class="notice error">Could not reach GitHub's release API
      (${err.message}). Get the app directly from
      <a href="https://github.com/${REPO}/releases">github.com/${REPO}/releases</a>.</p>`;
  }
}

loadRelease();
