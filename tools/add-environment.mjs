// Adds a remote environment to a running T3 Code desktop app, as if pasted into
// Settings → Connections → Add environment, by driving its UI over the Chrome
// DevTools Protocol. Depends on the dialog's labels; check it with --probe first.
//
// The app must have been started with a DevTools port (quit it first):
//   macOS:  open -g -b com.t3tools.t3code --args --remote-debugging-port=9229
//   Linux:  ~/Applications/T3-Code.AppImage --remote-debugging-port=9229 &
// Then run with the app's own Node (Node 22+ also works):
//   ELECTRON_RUN_AS_NODE=1 "<T3 Code binary>" tools/add-environment.mjs 9229 @/path/to/pair-url
// "@file" keeps the pairing link off the command line. Afterwards quit the app and
// start it normally, so the DevTools port is closed again.
const [port, pairingArg] = process.argv.slice(2);
const pairingUrl = pairingArg?.startsWith("@")
  ? (await import("node:fs")).readFileSync(pairingArg.slice(1), "utf8").trim()
  : pairingArg;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// DevTools answers before the window exists; wait for the app page.
let page;
for (const end = Date.now() + 60000; !page && Date.now() < end; await sleep(500)) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json().catch(() => []);
  page = targets.find((t) => t.type === "page" && t.url.startsWith("t3code://app"));
}
if (!page) throw new Error("no T3 app page appeared on the DevTools port");

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => ((ws.onopen = resolve), (ws.onerror = reject)));
let nextId = 1;
const pending = new Map();
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  pending.get(msg.id)?.(msg);
  pending.delete(msg.id);
};
const evaluate = (expression) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, (msg) =>
      msg.result?.exceptionDetails
        ? reject(new Error(JSON.stringify(msg.result.exceptionDetails)))
        : resolve(msg.result?.result?.value),
    );
    ws.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, awaitPromise: true, returnByValue: true } }));
  });
const waitFor = async (expression, what, ms = 20000) => {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(250)) {
    const value = await evaluate(expression);
    if (value) return value;
  }
  throw new Error(`timed out waiting for ${what}`);
};

// Visible-text lookup and React-compatible input filling.
await evaluate(`window.__t3 = {
  byText(sel, text, root = document) {
    return [...root.querySelectorAll(sel)].find((e) => e.textContent.trim() === text && e.offsetParent !== null);
  },
  fill(el, value) {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  },
  dialog() { return document.querySelector('[role="dialog"]'); },
}; true`);

// The app uses hash routes, and needs a few seconds after launch before the UI exists.
await waitFor(`!!document.querySelector('button[aria-label="Settings"], a[aria-label="Settings"]')`, "the app UI");
await evaluate(`location.hash = "#/settings/connections"; true`);
await waitFor(`!!document.querySelector('button[aria-label="Add environment"]')`, "the Add environment button");
await evaluate(`document.querySelector('button[aria-label="Add environment"]').click(); true`);
await waitFor(`!!document.querySelector('[role="dialog"] input[placeholder="backend.example.com"]')`, "the Add environment dialog");
console.log("dialog:", JSON.stringify(await evaluate(
  `[...__t3.dialog().querySelectorAll("input,button")].map((e) => e.tagName + ":" + (e.placeholder || e.textContent.trim()).slice(0, 40))`)));

if (pairingUrl === "--probe" || !pairingUrl) {
  await evaluate(`document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); true`);
  ws.close();
  process.exit(0);
}

// Pasting the link into Host fills the pairing code from it.
await evaluate(`__t3.fill(__t3.dialog().querySelector('input[placeholder="backend.example.com"]'), ${JSON.stringify(pairingUrl)}); true`);
await sleep(500);
if (!(await evaluate(`__t3.dialog().querySelector('input[placeholder="PAIRCODE"]')?.value ?? ""`))) {
  throw new Error("the pairing code was not filled in from the link");
}
await evaluate(`__t3.byText("button", "Add environment", __t3.dialog()).click(); true`);
// Done when the dialog closes; an error stays in the dialog.
const outcome = await waitFor(
  `(() => { const d = __t3.dialog(); if (!d) return "added";
     const err = [...d.querySelectorAll("p,div")].find((e) => e.children.length === 0 &&
       /could not|failed|error|invalid|expired|unsupported|update/i.test(e.textContent));
     return err && !/Adding/.test(d.textContent) ? "error: " + err.textContent.trim() : ""; })()`,
  "pairing to finish",
  45000,
);
console.log(outcome);
ws.close();
process.exit(outcome === "added" ? 0 : 1);
