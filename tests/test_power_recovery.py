import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("power_recovery", ROOT / "linux/power-recovery.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)
HELPER = (ROOT / "linux/power-recovery.js").read_text()

# The exact code emitted by the affected release, with unrelated module code omitted.
FIXTURE = '''import { En as tryPromise, } from "./Effect.mjs";
const adapter = {
startTurn: (turnInput) => {
 const goalCommand = turnInput.restartContinuationOfRunId === void 0 ? parseGoalCommand(turnInput.message) : null;
 if (goalCommand !== null) return runGoalCommand(turnInput, goalCommand);
 return gen$1(function* () {
 yield* startNativeTurn(turnInput, turnInput.restartContinuationOfRunId === void 0 ? yield* toCodexInput(turnInput) : []);
 }).pipe(mapError((cause) => cause));
},
steerTurn: () => {},
};
const continueRestartedRun = fn("RestartContinuation.continueRestartedRun")(function* (input) {
 return;
});
tapError$1(() => willRetry ? void_$1 : threads.recoverDelegatedTask(effect.threadId, sourceRunId));
effect.attemptCount >= maxAttempts ? yield* outbox.fail({});
const delay = {delayMs: Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))};
''' + f"const CONTINUE_PROMPT = {json.dumps(repair.OLD_CONTINUE_PROMPT)};\n"

# 0.1.8-nightly.20261109.4399 split the server into chunks. The same code lives in
# apps/server/dist/runtimeLayer-*.mjs, with different bundler collision suffixes.
SPLIT_FIXTURE = (FIXTURE
                 .replace('import { En as tryPromise, } from "./Effect.mjs";',
                          'import { vs as tapError, ws as tryPromise, } from "./Schema-D36BDnNk.mjs";\n'
                          'const used = tryPromise({ try: async () => 1, catch: (cause) => cause });')
                 .replace("tapError$1(() => willRetry ? void_$1 :", "tapError(() => willRetry ? void_ :"))
LAYOUTS = {"0.1.7-nightly.20261101.4016": FIXTURE, "0.1.8-nightly.20261109.4399": SPLIT_FIXTURE}

# The session code of 0.1.8-nightly.20261109.4433 (apps/server/dist/relayTracing-*.mjs),
# with unrelated module code omitted.
SESSION_FIXTURE = '''import { nf as days, of as hours } from "./Schema-D6xl61Zp.mjs";
const DEFAULT_SESSION_TTL = days(30);
        WHERE revoked_at IS NULL
          AND (expires_at > ${now} OR ${sql.in("session_id", connectedSessionIds)})
		if (!connected && row.value.expiresAt.epochMilliseconds <= now$6.epochMilliseconds) return none();
	const verify = fn("SessionStore.verify")(function* (token) {
			if (row.value.expiresAt.epochMilliseconds <= observedAt.epochMilliseconds) return yield* new SessionTokenExpiredError({
		if (claims.exp <= observedAt.epochMilliseconds) return yield* new SessionTokenExpiredError({
		if (claims.exp <= observedAt.epochMilliseconds) return yield* new WebSocketTokenExpiredError({
		if (row.value.expiresAt.epochMilliseconds <= observedAt.epochMilliseconds) return yield* new WebSocketSessionExpiredError({
				const remaining = current.expiresAt.epochMilliseconds - now$5.epochMilliseconds;
			return yield* sessions.issue({
				method: input?.proofKeyThumbprint ? "dpop-access-token" : "bearer-access-token",
				subject: grant.subject,
				scopes: grantedScopes,
				...input?.proofKeyThumbprint ? {
					proofKeyThumbprint: input.proofKeyThumbprint,
					ttl: hours(1)
				} : {},
				replaceActiveForSubjectAndMethod: grant.method === "desktop-bootstrap",
'''


def node(source):
    result = subprocess.run(["node", "--input-type=module", "-"], input=source,
                            text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class RecoveryTests(unittest.TestCase):
    def test_empty_codex_continuation_is_rejected_before_repair_and_sent_after(self):
        cases = [(source, repaired) for fixture in LAYOUTS.values()
                 for source, repaired in [(fixture, False), (repair.patch_bundle(fixture, HELPER), True)]]
        for source, repaired in cases:
            block = source[source.index("const adapter = {"):source.index("const continueRestartedRun")]
            if repair.MARKER in block:
                block = block[:block.index(repair.MARKER)]
            script = '''
import assert from 'node:assert/strict';
function gen$1(f) { return { pipe() { return f(); } }; }
function mapError(f) { return f; }
function parseGoalCommand() { return null; }
function* toCodexInput(input) { return [{type:'text', text:input.message.text}]; }
let received;
function* startNativeTurn(input, items) {
 if (!items.length) throw Error('EmptyInput');
 received = items;
}
''' + block + '''
const run = () => adapter.startTurn({restartContinuationOfRunId:'cut-run', message:{text:'Continue safely; check prior actions.'}}).next();
'''
            script += ("run(); assert.deepEqual(received, [{type:'text', text:'continue'}]);"
                       if repaired else "assert.throws(run, /EmptyInput/);")
            script += "adapter.startTurn({message:{text:'normal user input'}}).next(); assert.equal(received[0].text, 'normal user input');"
            node(script)

    def test_both_layouts_receive_the_same_semantic_patch(self):
        for version, fixture in LAYOUTS.items():
            with self.subTest(version=version):
                patched = repair.patch_bundle(fixture, HELPER)
                self.assertIn('const CONTINUE_PROMPT = "continue";', patched)
                self.assertIn('[{ type: "text", text: "continue" }]', patched)
                self.assertIn("yield* tryPromise({ try: t3RecoveryWaitForInternet", patched)
                tap = "tapError$1" if "tapError$1" in fixture else "tapError"
                void = "void_$1" if "void_$1" in fixture else "void_"
                self.assertIn(f'{tap}((cause) => willRetry || t3RecoveryWaiting("provider-runtime.continue", cause) '
                              f'? {void} : threads.recoverDelegatedTask(effect.threadId, sourceRunId))', patched)
                self.assertEqual(patched.count(repair.MARKER), 1)

    def test_offline_wait_has_no_attempt_limit_and_rejects_captive_portals(self):
        patched = repair.patch_bundle(FIXTURE, HELPER)
        self.assertIn('const CONTINUE_PROMPT = "continue";', patched)
        terminal = "effect.attemptCount >= maxAttempts && !t3RecoveryWaiting(effect.request.type, error)"
        delay = "t3RecoveryWaiting(effect.request.type, error) ? 30_000 : Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))"
        self.assertIn(terminal, patched)
        self.assertIn(delay, patched)
        node(HELPER + '''
const assert = (await import('node:assert/strict')).default;
let outcome = 'offline', calls = 0;
globalThis.fetch = async (url, options) => {
 calls++;
 assert.equal(options.redirect, 'error');
 assert.equal(options.credentials, 'omit');
 if (outcome === 'offline') throw Error('DNS not ready');
 return {status:outcome === 'portal' ? 200 : 204};
};
let clock = 0;
for (; clock <= 20 * 60 * 1000; clock += 30_000) {
 await assert.rejects(t3RecoveryWaitForInternet, /T3_POWER_RECOVERY_WAITING_FOR_INTERNET/);
 const effect = {request:{type:'provider-runtime.continue'}, attemptCount:clock / 30_000 + 1};
 const error = T3_RECOVERY_OFFLINE, maxAttempts = 5;
 assert.equal(TERMINAL, false);
 assert.equal(DELAY, 30_000);
}
outcome = 'portal';
await assert.rejects(t3RecoveryWaitForInternet, /T3_POWER_RECOVERY_WAITING_FOR_INTERNET/);
outcome = 'online';
await t3RecoveryWaitForInternet();
// Unrelated failures still use the ordinary finite budget.
const effect = {request:{type:'provider-turn.start'}, attemptCount:99};
const error = 'ordinary error', maxAttempts = 5;
assert.equal(TERMINAL, true);
assert.equal(t3RecoveryWaiting('provider-turn.start', T3_RECOVERY_OFFLINE), false);
'''.replace("TERMINAL", terminal).replace("DELAY", delay))

    def test_one_working_probe_is_enough_and_concurrent_threads_share_probes(self):
        node(HELPER + '''
const assert = (await import('node:assert/strict')).default;
let calls = 0;
globalThis.fetch = async (url) => {
 calls++;
 if (url.includes('gstatic')) throw Error('one site blocked');
 return {status:204};
};
await Promise.all([t3RecoveryWaitForInternet(), t3RecoveryWaitForInternet(), t3RecoveryWaitForInternet()]);
assert.equal(calls, 2);
''')

    def test_patch_is_idempotent_and_refuses_unrecognized_code(self):
        for fixture in LAYOUTS.values():
            patched = repair.patch_bundle(fixture, HELPER)
            self.assertEqual(repair.patch_bundle(patched, HELPER), patched)
            with self.assertRaises(ValueError):
                repair.patch_bundle(fixture.replace(" : []);", " : [different]);"), HELPER)
            with self.assertRaises(ValueError):
                repair.patch_bundle(fixture + fixture, HELPER)
            with self.assertRaises(ValueError):
                repair.patch_bundle(fixture.replace("willRetry ? void_", "willRetry ? other_"), HELPER)

    def test_paired_sessions_never_expire_but_other_sessions_do(self):
        patched = repair.patch_sessions(SESSION_FIXTURE)
        self.assertEqual(repair.patch_sessions(patched), patched)
        # New pairings: 100 years; DPoP keeps one hour; the dev and WebSocket-ticket checks stay.
        self.assertIn('} : grant.subject === "one-time-token" ? { ttl: T3_ANYWHERE_PAIRED_TTL } : {},', patched)
        self.assertIn("ttl: hours(1)", patched)
        self.assertIn("if (claims.exp <= observedAt.epochMilliseconds) return yield* new WebSocketTokenExpiredError", patched)
        self.assertIn("\t\t\tif (row.value.expiresAt.epochMilliseconds <= observedAt.epochMilliseconds) "
                      "return yield* new SessionTokenExpiredError", patched)
        for guarded in ("claims.exp <= observedAt.epochMilliseconds && !t3AnywherePaired(claims)",
                        "!connected && !t3AnywherePaired(row.value) &&",
                        "!t3AnywherePaired(row.value) && row.value.expiresAt.epochMilliseconds <= observedAt."
                        "epochMilliseconds) return yield* new WebSocketSessionExpiredError",
                        "t3AnywherePaired(current) ? 2147483647 :",
                        "OR (method = 'bearer-access-token' AND subject = 'one-time-token') OR"):
            self.assertIn(guarded, patched)
        predicate = repair.PAIRED_SESSION_HELPER.replace("days(36500)", "36500")
        verdicts = json.loads(node(predicate + """
console.log(JSON.stringify([
  {method: "bearer-access-token", subject: "one-time-token"},
  {method: "bearer-access-token", sub: "one-time-token"},
  {method: "bearer-access-token", subject: "cli-issued-session"},
  {method: "bearer-access-token", subject: "desktop-bootstrap"},
  {method: "dpop-access-token", subject: "one-time-token"},
  {method: "browser-session-cookie", subject: "one-time-token"},
].map(t3AnywherePaired)));"""))
        self.assertEqual(verdicts, [True, True, False, False, False, False])

    def test_mac_load_time_patch_matches_the_appimage_patch(self):
        # macos/paired-sessions.mjs patches the Mac's server in memory; it must make the same edit.
        script = (f"import {{ patchSessions }} from {json.dumps((ROOT / 'macos/paired-sessions.mjs').as_uri())};\n"
                  "const input = JSON.parse(require_input());\n"
                  "const out = input.map((s) => { try { return patchSessions(s); } catch (e) { return null; } });\n"
                  "console.log(JSON.stringify(out));\n")
        cases = [SESSION_FIXTURE, SESSION_FIXTURE.replace("days(30)", "days(31)"), SESSION_FIXTURE + SESSION_FIXTURE]
        script = script.replace("require_input()", json.dumps(json.dumps(cases)))
        mac = json.loads(node(script))
        self.assertEqual(mac[0], repair.patch_sessions(SESSION_FIXTURE))
        self.assertEqual(mac[1:], [None, None])

    def test_session_patch_refuses_unrecognized_code(self):
        for changed in (SESSION_FIXTURE.replace("days(30)", "days(31)"),
                        SESSION_FIXTURE.replace("ttl: hours(1)", "ttl: hours(2)"),
                        SESSION_FIXTURE.replace("const remaining = current.", "const left = current."),
                        SESSION_FIXTURE.replace("nf as days", "nf as durationDays"),
                        SESSION_FIXTURE + SESSION_FIXTURE):
            with self.assertRaises(ValueError):
                repair.patch_sessions(changed)

    def test_patched_module_is_the_one_server_chunk_with_the_restart_continuation(self):
        def archive(directory, files):
            path = Path(directory) / "app.asar"
            header, blob = {"files": {}}, b""
            for name, data in files.items():
                node = header
                *folders, leaf = name.split("/")
                for folder in folders:
                    node = node["files"].setdefault(folder, {"files": {}})
                node["files"][leaf] = {"size": len(data), "offset": str(len(blob))}
                blob += data
            raw = json.dumps(header).encode()
            padded = raw + b"\0" * (-len(raw) % 4)
            pickle = struct.pack("<II", len(padded) + 4, len(raw)) + padded
            path.write_bytes(struct.pack("<II", 4, len(pickle)) + pickle + blob)
            return (path, *repair.read_asar(path))

        layouts = {
            "single": {"apps/server/dist/bin.mjs": b"import './binCli-A.mjs';",
                       "apps/server/dist/binCli-A.mjs": FIXTURE.encode()},
            "split": {"apps/server/dist/binCli-B.mjs": b"export const cli = 1;",
                      "apps/server/dist/runtimeLayer-C.mjs": SPLIT_FIXTURE.encode(),
                      "apps/web/dist/x.mjs": SPLIT_FIXTURE.encode()},
        }
        expected = {"single": "apps/server/dist/binCli-A.mjs", "split": "apps/server/dist/runtimeLayer-C.mjs"}
        for layout, files in layouts.items():
            with tempfile.TemporaryDirectory() as directory:
                self.assertEqual(repair.restart_module(*archive(directory, files)), expected[layout])
        with tempfile.TemporaryDirectory() as directory:
            twice = {"apps/server/dist/a.mjs": FIXTURE.encode(), "apps/server/dist/b.mjs": FIXTURE.encode()}
            with self.assertRaises(ValueError):
                repair.restart_module(*archive(directory, twice))

    def test_refusal_is_recorded_for_monitors_and_a_new_helper_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            app, state = directory / "T3-Code.AppImage", directory / "state"
            app.write_text("#!/bin/sh\nexit 1\n")
            app.chmod(0o755)
            with self.assertRaises(Exception):
                repair.apply(app, state)
            failed = json.loads((state / "failed.json").read_text())
            stamp = app.stat()
            self.assertEqual(failed["identity"], [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns])
            self.assertEqual(failed["patchLevel"], repair.PATCH_LEVEL)
            self.assertEqual(failed["helperSha256"], repair.helper_fingerprint())
            self.assertIn("at", failed)
            self.assertIn("appVersion", failed)
            with self.assertRaisesRegex(ValueError, "previous repair refused"):
                repair.apply(app, state)
            failed["helperSha256"] = "an older helper"
            (state / "failed.json").write_text(json.dumps(failed))
            with self.assertRaises(Exception) as retried:
                repair.apply(app, state)
            self.assertNotIn("previous repair refused", str(retried.exception))
            report = repair.status(app, state)
            self.assertFalse(report["currentAppMatches"])
            self.assertTrue(report["failedForCurrentApp"])
            self.assertFalse(report["ok"])

    def test_status_is_read_only_and_matches_the_installed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            app, state = directory / "T3-Code.AppImage", directory / "state"
            state.mkdir()
            app.write_bytes(b"repaired")
            stamp = app.stat()
            record = {"patchLevel": repair.PATCH_LEVEL, "installedSha256": hashlib.sha256(b"repaired").hexdigest(),
                      "identity": [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns]}
            (state / "installed.json").write_text(json.dumps(record))
            before = sorted(os.listdir(state))
            report = repair.status(app, state)
            self.assertTrue(report["currentAppMatches"])
            self.assertTrue(report["ok"])
            self.assertFalse(report["failedForCurrentApp"])
            self.assertEqual(sorted(os.listdir(state)), before)
            replacement = directory / "new"
            replacement.write_bytes(b"a new download")
            replacement.replace(app)
            self.assertFalse(repair.status(app, state)["currentAppMatches"])
            self.assertFalse(repair.status(app, directory / "empty")["ok"])

    def test_asar_rewrite_preserves_neighboring_files_offsets_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.asar"
            header = {"files": {
                "first": {"size": 3, "offset": "0"},
                "middle": {"size": 4, "offset": "3"},
                "last": {"size": 3, "offset": "7"},
                "unpacked": {"size": 20, "unpacked": True},
                "link": {"link": "first"},
            }}
            raw = json.dumps(header).encode()
            padded = raw + b"\0" * (-len(raw) % 4)
            pickle = struct.pack("<II", len(padded) + 4, len(raw)) + padded
            path.write_bytes(struct.pack("<II", 4, len(pickle)) + pickle + b"abcDEFGxyz")
            for replacement in [b"much longer replacement", b"z"]:
                repair.rewrite_member(path, "middle", replacement)
                header, base = repair.read_asar(path)
                self.assertEqual(repair.read_member(path, header, base, "first"), b"abc")
                self.assertEqual(repair.read_member(path, header, base, "middle"), replacement)
                self.assertEqual(repair.read_member(path, header, base, "last"), b"xyz")
                self.assertEqual(header["files"]["middle"]["integrity"]["hash"],
                                 hashlib.sha256(replacement).hexdigest())


if __name__ == "__main__":
    unittest.main()
