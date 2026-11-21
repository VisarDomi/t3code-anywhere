import hashlib
import importlib.util
import json
import time
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import unittest.mock

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
# 0.1.10-nightly.20261112.4580 passes the source run as an object.
OBJECT_RUN_FIXTURE = SPLIT_FIXTURE.replace("recoverDelegatedTask(effect.threadId, sourceRunId)",
                                           "recoverDelegatedTask(effect.threadId, { sourceRunId })")
LAYOUTS = {"0.1.7-nightly.20261101.4016": FIXTURE, "0.1.8-nightly.20261109.4399": SPLIT_FIXTURE,
           "0.1.10-nightly.20261112.4580": OBJECT_RUN_FIXTURE}

# 0.1.11-nightly.20261119.4928 moved the Codex adapter into its own chunk
# (apps/server/dist/server-*.mjs), where a resumed turn counts as a continuation too, and
# added conditions to the retry exhaustion check.
ADAPTER_START = OBJECT_RUN_FIXTURE.index("const adapter = {")
ADAPTER_END = OBJECT_RUN_FIXTURE.index("const continueRestartedRun")
CODEX_CHUNK_FIXTURE = '''#!/usr/bin/env node
import { x as gen$1 } from "./Effect.mjs";
const startNativeTurn = fn("CodexAdapterV2.startNativeTurn")(function* (turnInput, codexInput) {});
const adapter = {
startTurn: (turnInput) => {
 const continuation = turnInput.restartContinuationOfRunId !== void 0 || turnInput.resume === true;
 const goalCommand = !continuation ? parseGoalCommand(turnInput.message) : null;
 if (goalCommand !== null) return runGoalCommand(turnInput, goalCommand);
 return gen$1(function* () {
 yield* startNativeTurn(turnInput, !continuation ? yield* toCodexInput(turnInput) : []);
 }).pipe(mapError((cause) => cause));
},
steerTurn: () => {},
};
'''
RESTART_CHUNK_FIXTURE = (OBJECT_RUN_FIXTURE[:ADAPTER_START] + OBJECT_RUN_FIXTURE[ADAPTER_END:]).replace(
    "effect.attemptCount >= maxAttempts ? yield* outbox.fail({});",
    "effect.attemptCount >= maxAttempts && (!ownsStartingRun(effect.request.type) || cannotSettleRun(exit$1.cause)) ? yield* outbox.fail({});")

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

    def test_codex_chunk_of_20261119_says_continue_only_for_restart_continuations(self):
        self.assertFalse(repair.starts_codex_turns(RESTART_CHUNK_FIXTURE))
        patched = repair.patch_codex(CODEX_CHUNK_FIXTURE)
        self.assertEqual(repair.patch_codex(patched), patched)
        self.assertTrue(patched.startswith("#!/usr/bin/env node\n" + repair.CODEX_MARKER + "\n"))  # the shebang stays first
        for source, repaired in ((CODEX_CHUNK_FIXTURE, False), (patched, True)):
            block = source[source.index("const adapter = {"):]
            script = '''
import assert from 'node:assert/strict';
function gen$1(f) { return { pipe() { return f(); } }; }
function mapError(f) { return f; }
function parseGoalCommand() { return null; }
function* toCodexInput(input) { return [{type:'text', text:input.message.text}]; }
let received;
function* startNativeTurn(input, items) { received = items; }
''' + block + '''
adapter.startTurn({restartContinuationOfRunId:'cut-run', message:{text:'x'}}).next();
const restart = received;
adapter.startTurn({resume:true, message:{text:'x'}}).next();
assert.deepEqual(received, []);
adapter.startTurn({message:{text:'normal user input'}}).next();
assert.equal(received[0].text, 'normal user input');
'''
            script += ("assert.deepEqual(restart, [{type:'text', text:'continue'}]);" if repaired
                       else "assert.deepEqual(restart, []);")
            node(script)
        with self.assertRaisesRegex(ValueError, "Codex turn start"):
            repair.patch_codex("const nothing = 1;")

    def test_restart_chunk_of_20261119_keeps_its_new_exhaustion_conditions(self):
        patched = repair.patch_bundle(RESTART_CHUNK_FIXTURE, HELPER)
        self.assertNotIn(repair.CODEX_MARKER, patched)
        self.assertIn("effect.attemptCount >= maxAttempts && !t3RecoveryWaiting(effect.request.type, error) "
                      "&& (!ownsStartingRun(effect.request.type) || cannotSettleRun(exit$1.cause)) ? yield* outbox.fail",
                      patched)
        self.assertIn("yield* tryPromise({ try: t3RecoveryWaitForInternet", patched)
        self.assertIn('const CONTINUE_PROMPT = "continue";', patched)

    def test_both_layouts_receive_the_same_semantic_patch(self):
        for version, fixture in LAYOUTS.items():
            with self.subTest(version=version):
                patched = repair.patch_bundle(fixture, HELPER)
                self.assertIn('const CONTINUE_PROMPT = "continue";', patched)
                self.assertIn('[{ type: "text", text: "continue" }]', patched)
                self.assertIn("yield* tryPromise({ try: t3RecoveryWaitForInternet", patched)
                tap = "tapError$1" if "tapError$1" in fixture else "tapError"
                void = "void_$1" if "void_$1" in fixture else "void_"
                run = "{ sourceRunId }" if "{ sourceRunId }" in fixture else "sourceRunId"
                self.assertIn(f'{tap}((cause) => willRetry || t3RecoveryWaiting("provider-runtime.continue", cause) '
                              f'? {void} : threads.recoverDelegatedTask(effect.threadId, {run}))', patched)
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
            changed = fixture.replace(" : []);", " : [different]);")
            # Unrecognised Codex code is no longer this chunk's: the AppImage then has no module
            # that starts Codex turns (codex_module), and patch_codex refuses it.
            self.assertFalse(repair.starts_codex_turns(changed))
            with self.assertRaises(ValueError):
                repair.patch_codex(changed)
            with self.assertRaises(ValueError):
                repair.patch_bundle(fixture + fixture, HELPER)
            with self.assertRaises(ValueError):
                repair.patch_bundle(fixture.replace("willRetry ? void_", "willRetry ? other_"), HELPER)

    def test_pairing_mode_issues_long_sessions_and_leaves_validation_alone(self):
        patched = repair.patch_sessions(SESSION_FIXTURE)
        self.assertEqual(repair.patch_sessions(patched), patched)
        # New pairings: 100 years; DPoP keeps one hour.
        self.assertIn('} : grant.subject === "one-time-token" ? { ttl: T3_ANYWHERE_PAIRED_TTL } : {},', patched)
        self.assertIn("ttl: hours(1)", patched)
        self.assertIn("const T3_ANYWHERE_PAIRED_TTL = days(36500);", patched)
        # Every expiry check is upstream's: a device stays signed in because its session
        # really lasts that long, so an unmodified build accepts it too.
        added = [line for line in patched.splitlines() if line not in SESSION_FIXTURE.splitlines()]
        self.assertEqual(len(added), 4, added)
        for check in ("claims.exp <= observedAt", "expiresAt.epochMilliseconds <=", "expires_at > ${now}",
                      "const remaining = current.expiresAt"):
            self.assertEqual([line for line in patched.splitlines() if check in line],
                             [line for line in SESSION_FIXTURE.splitlines() if check in line])

    def test_pairing_mode_is_off_by_default_and_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            self.assertFalse(repair.pairing_mode(state))
            marker = state / "pairing-mode"
            marker.touch()
            self.assertTrue(repair.pairing_mode(state))
            old = time.time() - (repair.PAIRING_MODE_HOURS * 3600 + 60)
            os.utime(marker, (old, old))
            self.assertFalse(repair.pairing_mode(state))
            self.assertFalse(marker.exists())

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
        layouts["codex-chunk"] = {"apps/server/dist/runtimeLayer-D.mjs": RESTART_CHUNK_FIXTURE.encode(),
                                  "apps/server/dist/server-E.mjs": CODEX_CHUNK_FIXTURE.encode()}
        expected = {"single": "apps/server/dist/binCli-A.mjs", "split": "apps/server/dist/runtimeLayer-C.mjs",
                    "codex-chunk": "apps/server/dist/runtimeLayer-D.mjs"}
        codex = dict(expected, **{"codex-chunk": "apps/server/dist/server-E.mjs"})
        for layout, files in layouts.items():
            with tempfile.TemporaryDirectory() as directory:
                found = archive(directory, files)
                restart = repair.restart_module(*found)
                self.assertEqual(restart, expected[layout])
                self.assertEqual(repair.codex_module(*found, restart), codex[layout])
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
            self.assertFalse(failed["pairingMode"])
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

    def test_a_refused_build_starts_one_porting_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            app, state, bin_dir = directory / "T3-Code.AppImage", directory / "state", directory / "bin"
            app.write_text("#!/bin/sh\nexit 1\n")
            app.chmod(0o755)
            bin_dir.mkdir()
            calls, message = directory / "calls", directory / "message"
            (bin_dir / "t3").write_text(f'#!/bin/sh\necho "$@" >> {calls}\ncat > {message}\n'
                                        'echo \'{"threadId":"thread-1"}\'\n')
            (bin_dir / "t3").chmod(0o755)
            with self.assertRaises(Exception):
                repair.apply(app, state)
            env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "T3CODE_ANYWHERE_CHECKOUT": str(ROOT)}
            with unittest.mock.patch.dict(os.environ, env):
                self.assertEqual(repair.request_port(app, state)["thread"], "thread-1")
                self.assertEqual(repair.request_port(app, state)["thread"], "thread-1")  # once per build
            self.assertEqual(len(calls.read_text().splitlines()), 1)
            self.assertIn(f"thread start {ROOT} - --json --title Port T3 power recovery", calls.read_text())
            text = message.read_text()
            self.assertIn("Do not restart or quit T3", text)
            self.assertIn(str(ROOT / "linux/power-recovery.py"), text)
            self.assertEqual(repair.status(app, state)["portRequest"]["thread"], "thread-1")
            (state / "port-request.json").unlink()
            (state / "no-auto-port").touch()
            with unittest.mock.patch.dict(os.environ, env):
                self.assertIsNone(repair.request_port(app, state))
            self.assertEqual(len(calls.read_text().splitlines()), 1)

    def test_only_the_installed_builds_original_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            originals = Path(directory)
            keep = originals / "current.AppImage"
            for name in ("old-1.AppImage", "old-2.AppImage", "current.AppImage", "notes.txt"):
                (originals / name).write_text(name)
            repair.prune_originals(originals, keep)
            self.assertEqual(sorted(p.name for p in originals.iterdir()), ["current.AppImage", "notes.txt"])

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
