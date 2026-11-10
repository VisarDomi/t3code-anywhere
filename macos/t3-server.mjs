// Runs the Mac's T3 Code server as a background service, with paired-device sessions
// that never expire (t3code-anywhere, owner request 2026-11-10).
//
// The signed app is not modified. Electron strips --import from NODE_OPTIONS in a
// packaged app, so the desktop app's own server cannot be patched without editing the
// bundle. This script is started with the app's own binary in Node mode
// (ELECTRON_RUN_AS_NODE=1, like the `t3` command), registers a module hook that patches
// the session module in memory as it loads, then starts the app's server entry.
//
// A changed upstream layout is recorded in the status file and the server starts
// unpatched: remote access then follows upstream's 30-day sessions until the patch is
// updated. When the app is updated on disk, the server exits so launchd restarts it on
// the new release, patched again.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { registerHooks } from "node:module";
import { pathToFileURL } from "node:url";
import { patchSessions, SESSION_MODULE_ANCHOR } from "./paired-sessions.mjs";

const app = process.env.T3_ANYWHERE_APP ?? "/Applications/T3 Code (Nightly).app";
const resources = process.env.T3_ANYWHERE_RESOURCES ?? path.join(app, "Contents/Resources");
const asar = path.join(resources, "app.asar");
const entry = path.join(asar, "apps/server/dist/bin.mjs");
const statusFile = process.env.T3_ANYWHERE_STATUS ??
  path.join(os.homedir(), ".local/share/t3code-server/status.json");
const releaseMarker = process.env.T3_ANYWHERE_RELEASE_MARKER ?? path.join(app, "Contents/Info.plist");

function readVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(asar, "package.json"), "utf8")).version;
  } catch {
    return null;
  }
}

const version = readVersion();
// Other commands (`auth session list` and so on) also work through this script, patched,
// but only the server writes the status file that monitoring reads.
const serving = process.argv[2] === "serve";

function writeStatus(data) {
  if (!serving) return;
  try {
    fs.mkdirSync(path.dirname(statusFile), { recursive: true, mode: 0o700 });
    const temp = `${statusFile}.tmp`;
    fs.writeFileSync(temp, JSON.stringify({ ...data, version, pid: process.pid, at: new Date().toISOString() }, null, 2) + "\n");
    fs.renameSync(temp, statusFile);
  } catch (error) {
    console.error(`t3code-server: could not write ${statusFile}: ${error.message}`);
  }
}

writeStatus({ ok: false, state: "starting" });

registerHooks({
  load(url, context, nextLoad) {
    const result = nextLoad(url, context);
    if (!url.startsWith("file:") || !url.includes("/apps/server/dist/") || result.source == null) return result;
    const text = typeof result.source === "string" ? result.source : Buffer.from(result.source).toString("utf8");
    if (!text.includes(SESSION_MODULE_ANCHOR)) return result;
    const module = path.basename(new URL(url).pathname);
    try {
      const source = patchSessions(text);
      writeStatus({ ok: true, state: "patched", module });
      return { ...result, source };
    } catch (error) {
      console.error(`t3code-server: session patch refused for ${module}: ${error.message}`);
      writeStatus({ ok: false, state: "refused", module, error: error.message });
      return result;
    }
  },
});

// A new release replaces the app bundle; exit so launchd starts the new one.
function releaseIdentity() {
  try {
    const stat = fs.statSync(releaseMarker);
    return `${stat.ino}:${stat.size}:${stat.mtimeMs}`;
  } catch {
    return null;
  }
}
const startedRelease = releaseIdentity();
setInterval(() => {
  const current = releaseIdentity();
  if (startedRelease && current && current !== startedRelease) {
    console.error("t3code-server: the app was updated; restarting on the new release");
    process.kill(process.pid, "SIGTERM");
  }
}, 60_000).unref();

// A server already owning the data folder (the desktop app's own, while its Local
// environment is on) would make this one exit at once and launchd retry every few
// seconds. Wait for it cheaply instead; the service takes over when it stops.
function ownerPid() {
  const home = process.env.T3CODE_HOME ?? path.join(os.homedir(), ".t3");
  try {
    const pid = JSON.parse(fs.readFileSync(path.join(home, "userdata/server-runtime.json"), "utf8")).pid;
    if (!Number.isInteger(pid) || pid === process.pid) return null;
    process.kill(pid, 0);
    const command = execFileSync("/bin/ps", ["-o", "command=", "-p", String(pid)], { encoding: "utf8" });
    return /T3 Code|apps\/server\/dist\/bin\.mjs|t3-server\.mjs/.test(command) ? pid : null;
  } catch {
    return null;
  }
}
if (process.argv[2] === "serve") {
  for (let pid = ownerPid(), told = false; pid !== null; pid = ownerPid()) {
    if (!told) {
      writeStatus({ ok: false, state: "waiting", error: `T3 server ${pid} owns the data folder; switch off Local environment in the desktop app` });
      told = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 15_000));
  }
}

// bin.mjs only runs when it is the main module (import.meta.main), so start its CLI
// the way bin.mjs does: import the CLI chunk it names and run the command.
const bin = fs.readFileSync(entry, "utf8");
const chunks = [...bin.matchAll(/import\("\.\/(binMain-[\w-]+\.mjs)"\)/g)].map((match) => match[1]);
if (chunks.length !== 1 || !bin.includes("runCliCommand")) {
  writeStatus({ ok: false, state: "unsupported-entry", error: `expected one CLI chunk in bin.mjs, found ${chunks.length}` });
  throw new Error("t3code-server: unsupported bin.mjs layout");
}
process.argv[1] = entry;
const { runCliCommand } = await import(pathToFileURL(path.join(path.dirname(entry), chunks[0])).href);
await runCliCommand();
