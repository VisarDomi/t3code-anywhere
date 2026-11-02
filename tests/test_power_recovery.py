import hashlib
import importlib.util
import json
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


def node(source):
    result = subprocess.run(["node", "--input-type=module", "-"], input=source,
                            text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout


class RecoveryTests(unittest.TestCase):
    def test_empty_codex_continuation_is_rejected_before_repair_and_sent_after(self):
        for source, repaired in [(FIXTURE, False), (repair.patch_bundle(FIXTURE, HELPER), True)]:
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
        patched = repair.patch_bundle(FIXTURE, HELPER)
        self.assertEqual(repair.patch_bundle(patched, HELPER), patched)
        with self.assertRaises(ValueError):
            repair.patch_bundle(FIXTURE.replace(" : []);", " : [different]);"), HELPER)
        with self.assertRaises(ValueError):
            repair.patch_bundle(FIXTURE + FIXTURE, HELPER)

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
