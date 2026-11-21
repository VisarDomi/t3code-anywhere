#!/usr/bin/env python3
"""Repair the desktop AppImage atomically; never open T3's state database.

Only exact, singly occurring bundle anchors are accepted. Original AppImages are
retained outside the checkout. A changed upstream layout is an error, not a best
effort binary edit. A mounted, running AppImage keeps its original inode.

Supported layouts: the single server bundle of 0.1.7-nightly.20261101.4016
(`apps/server/dist/binCli-*.mjs`), the code-split bundle of
0.1.8-nightly.20261109.4399 (`apps/server/dist/runtimeLayer-*.mjs`), and
0.1.11-nightly.20261119.4928, whose Codex adapter moved to its own chunk
(`apps/server/dist/server-*.mjs`) and whose retry exhaustion gained conditions. The
patched modules are the one server chunk that defines the restart continuation and
the one that starts a Codex turn (the same chunk before 20261119).

A build this helper refuses is ported automatically: the refusal starts one T3 thread
on this machine (`t3 thread start`) that ports the helper in its source checkout,
tests, installs and applies it (see `request_port`; `no-auto-port` in the state
folder switches that off).

Pairing mode (owner request, 2026-11-12) is off unless switched on with
`--pairing-mode on`, and switches itself off after 24 hours. While it is on, the
build also makes a pairing link hand out a 100-year session instead of 30 days
(one edit in the server chunk that defines `SessionStore.verify`). T3 honours the
expiry it signed, so a device paired in that mode stays signed in on every later,
unmodified build; nothing has to be re-applied after an update. Pair, switch it
off, done: the normal build contains no session change.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

PATCH_LEVEL = 5
MARKER = "// t3code-anywhere power recovery v2"
SESSION_MARKER = "// t3code-anywhere paired sessions v1"
HERE = Path(__file__).resolve().parent
RESTART_MODULE_ANCHOR = 'fn("RestartContinuation.continueRestartedRun")'
SESSION_MODULE_ANCHOR = 'fn("SessionStore.verify")'
CODEX_MARKER = "// t3code-anywhere power recovery: restart continuations say continue"
CONTINUE_INPUT = '[{ type: "text", text: "continue" }]'
# How a Codex turn starts, per layout: upstream gives a restart continuation no input, which
# Codex rejects; the repair sends the text "continue".
CODEX_TURN_STARTS = (
    # Through 0.1.10: only a restart continuation is a continuation.
    ("yield* startNativeTurn(turnInput, turnInput.restartContinuationOfRunId === void 0 ? yield* toCodexInput(turnInput) : []);",
     "yield* startNativeTurn(turnInput, turnInput.restartContinuationOfRunId === void 0 ? yield* toCodexInput(turnInput) : "
     + CONTINUE_INPUT + ");"),
    # 0.1.11-nightly.20261119.4928: a resumed turn is a continuation too and keeps upstream's input.
    ("yield* startNativeTurn(turnInput, !continuation ? yield* toCodexInput(turnInput) : []);",
     "yield* startNativeTurn(turnInput, !continuation ? yield* toCodexInput(turnInput) : "
     "turnInput.restartContinuationOfRunId !== void 0 ? " + CONTINUE_INPUT + " : []);"),
)
PAIRED_SESSION_HELPER = (
    SESSION_MARKER + "\n"
    "// Pairing mode: a device paired now keeps its session until it is revoked.\n"
    "const T3_ANYWHERE_PAIRED_TTL = days(36500);\n"
)
PAIRING_MODE_HOURS = 24
OLD_CONTINUE_PROMPT = "Continue where you left off. Your last turn was cut short, so a command or other action it started may have finished or may still be running. Before you repeat one that changes state, confirm it did not take effect and is not still running; if you cannot tell, say so instead of repeating it."


def replace_one(source, old, new):
    count = source.count(old)
    if count != 1:
        raise ValueError(f"unsupported bundle: expected one {old[:100]!r}, found {count}")
    return source.replace(old, new, 1)


def starts_codex_turns(source):
    return CODEX_MARKER in source or any(old in source for old, _ in CODEX_TURN_STARTS)


def patch_codex(source):
    """A restart continuation reaches Codex as the text "continue"."""
    if CODEX_MARKER in source:
        return source
    for old, new in CODEX_TURN_STARTS:
        if source.count(old) == 1:
            source = source.replace(old, new, 1)
            # The marker goes first, after a shebang (the 20261119 chunk is the server's entry).
            shebang, rest = (source.split("\n", 1) if source.startswith("#!") else ("", source))
            return (shebang + "\n" if shebang else "") + CODEX_MARKER + "\n" + rest
    raise ValueError("unsupported bundle: expected one Codex turn start for restart continuations, found 0")


def patch_bundle(source, helper):
    """The restart-continuation chunk; also its Codex turn start where the two share a chunk."""
    if MARKER in source:
        return source
    if starts_codex_turns(source):
        source = patch_codex(source)
    source = replace_one(source, f"const CONTINUE_PROMPT = {json.dumps(OLD_CONTINUE_PROMPT)};",
                         'const CONTINUE_PROMPT = "continue";')
    anchor = 'const continueRestartedRun = fn("RestartContinuation.continueRestartedRun")(function* (input) {\n'
    source = replace_one(
        source, anchor,
        MARKER + "\n" + helper + "\n" + anchor +
        "\tyield* tryPromise({ try: t3RecoveryWaitForInternet, catch: (cause) => cause });\n",
    )
    # Waiting for the internet must neither settle a delegated task nor use up
    # the effect worker's ordinary five-attempt failure budget.
    # The bundler's collision suffixes differ between layouts (tapError$1/void_$1
    # in the single bundle, tapError/void_ in the split chunk); the code is the same.
    # 20261112 passes the run as `{ sourceRunId }` instead of `sourceRunId`.
    retry_tap = re.compile(
        r"(tapError(?:\$\d+)?)\(\(\) => willRetry \? (void_(?:\$\d+)?) : "
        r"threads\.recoverDelegatedTask\(effect\.threadId, (sourceRunId|\{ sourceRunId \})\)\)")
    matches = retry_tap.findall(source)
    if len(matches) != 1:
        raise ValueError(f"unsupported bundle: expected one delegated-task recovery tapError, found {len(matches)}")
    tap, void, run = matches[0]
    source = retry_tap.sub(
        lambda _: f'{tap}((cause) => willRetry || t3RecoveryWaiting("provider-runtime.continue", cause) '
                  f'? {void} : threads.recoverDelegatedTask(effect.threadId, {run}))',
        source, count=1)
    # 20261119 added conditions after the attempt check; the wait goes right after it.
    source = replace_one(
        source,
        "effect.attemptCount >= maxAttempts ",
        "effect.attemptCount >= maxAttempts && !t3RecoveryWaiting(effect.request.type, error) ",
    )
    source = replace_one(
        source,
        "delayMs: Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))",
        "delayMs: t3RecoveryWaiting(effect.request.type, error) ? 30_000 : Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))",
    )
    if "as tryPromise," not in source or "tryPromise({" not in source:
        raise ValueError("unsupported bundle: missing Effect.tryPromise import")
    return source


def patch_sessions(source):
    """Pairing mode: a pairing link issues a 100-year session instead of 30 days."""
    if SESSION_MARKER in source:
        return source
    if not re.search(r"\bas days\b", source):
        raise ValueError("unsupported bundle: missing Duration.days import")
    source = replace_one(source, "const DEFAULT_SESSION_TTL = days(30);\n",
                         "const DEFAULT_SESSION_TTL = days(30);\n" + PAIRED_SESSION_HELPER)
    exchange = re.compile(r'(ttl: hours\(1\)\s*\} : )\{\}(,\s*replaceActiveForSubjectAndMethod: '
                          r'grant\.method === "desktop-bootstrap",)')
    if len(exchange.findall(source)) != 1:
        raise ValueError("unsupported bundle: expected one pairing-link session exchange")
    return exchange.sub(r'\1grant.subject === "one-time-token" ? { ttl: T3_ANYWHERE_PAIRED_TTL } : {}\2',
                        source, count=1)


def pairing_mode(state):
    """True while the owner's pairing-mode switch is on; it expires by itself."""
    marker = state / "pairing-mode"
    try:
        age = time.time() - marker.stat().st_mtime
    except FileNotFoundError:
        return False
    if age > PAIRING_MODE_HOURS * 3600:
        marker.unlink(missing_ok=True)
        return False
    return True


def find_module(archive, header, base, anchor, what):
    found = []
    for name, entry in entries(header):
        if (name.startswith("apps/server/dist/") and name.endswith(".mjs") and "offset" in entry
                and not entry.get("unpacked")):
            if anchor.encode() in read_member(archive, header, base, name):
                found.append(name)
    if len(found) != 1:
        raise ValueError(f"unsupported AppImage: expected one server module with {what}, found {len(found)}")
    return found[0]


def restart_module(archive, header, base):
    """Return the one server module that owns the restart continuation."""
    return find_module(archive, header, base, RESTART_MODULE_ANCHOR, "the restart continuation")


def codex_module(archive, header, base, restart):
    """The one server module that starts Codex turns: the restart module itself before 20261119."""
    if starts_codex_turns(read_member(archive, header, base, restart).decode()):
        return restart
    found = [name for name, entry in entries(header)
             if name.startswith("apps/server/dist/") and name.endswith(".mjs") and "offset" in entry
             and not entry.get("unpacked") and starts_codex_turns(read_member(archive, header, base, name).decode())]
    if len(found) != 1:
        raise ValueError(f"unsupported AppImage: expected one server module that starts Codex turns, found {len(found)}")
    return found[0]


def session_module(archive, header, base):
    """Return the one server module that verifies session tokens."""
    return find_module(archive, header, base, SESSION_MODULE_ANCHOR, "the session store")


def helper_fingerprint():
    """A changed helper retries a bundle that an older helper refused."""
    hasher = hashlib.sha256()
    for name in ("power-recovery.py", "power-recovery.js"):
        hasher.update((HERE / name).read_bytes())
    return hasher.hexdigest()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_asar(path):
    with path.open("rb") as stream:
        a, header_size, pickle_size, json_size = struct.unpack("<4I", stream.read(16))
        if a != 4 or header_size != pickle_size + 4 or not 0 < json_size <= header_size - 8:
            raise ValueError("invalid ASAR header")
        header = json.loads(stream.read(json_size))
    return header, 8 + header_size


def entries(header, prefix=""):
    for name, item in header.get("files", {}).items():
        path = f"{prefix}/{name}" if prefix else name
        if "files" in item:
            yield from entries(item, path)
        else:
            yield path, item


def read_member(path, header, base, name):
    entry = dict(entries(header))[name]
    with path.open("rb") as stream:
        stream.seek(base + int(entry["offset"]))
        return stream.read(entry["size"])


def rewrite_member(path, name, replacement):
    header, base = read_asar(path)
    member = dict(entries(header))[name]
    start, old_size = int(member["offset"]), member["size"]
    delta = len(replacement) - old_size
    for _, entry in entries(header):
        if "offset" in entry and int(entry["offset"]) >= start + old_size:
            entry["offset"] = str(int(entry["offset"]) + delta)
    member["size"] = len(replacement)
    block_size = member.get("integrity", {}).get("blockSize", 4 * 1024 * 1024)
    member["integrity"] = {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(replacement).hexdigest(),
        "blockSize": block_size,
        "blocks": [hashlib.sha256(replacement[i:i + block_size]).hexdigest()
                   for i in range(0, len(replacement), block_size)],
    }
    raw_header = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
    padded = raw_header + b"\0" * (-len(raw_header) % 4)
    pickle_header = struct.pack("<II", len(padded) + 4, len(raw_header)) + padded
    output = path.with_suffix(".asar.tmp")
    with path.open("rb") as original, output.open("wb") as target:
        target.write(struct.pack("<II", 4, len(pickle_header)))
        target.write(pickle_header)
        original.seek(base)
        # Copy ranges without holding a complete archive in memory.
        remaining = start
        while remaining:
            block = original.read(min(remaining, 1024 * 1024))
            if not block:
                raise ValueError("truncated ASAR")
            target.write(block)
            remaining -= len(block)
        target.write(replacement)
        original.seek(old_size, 1)
        shutil.copyfileobj(original, target)
        target.flush()
        os.fsync(target.fileno())
    shutil.copymode(path, output)
    output.replace(path)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def apply(app, state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "repair.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stamp = app.stat()
        identity = [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns]
        record_path = state / "installed.json"
        pairing = pairing_mode(state)
        record = None
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if (record.get("identity") == identity and record.get("patchLevel") == PATCH_LEVEL
                    and record.get("pairingMode", False) == pairing):
                return record
        failed_path = state / "failed.json"
        fingerprint = helper_fingerprint()
        if failed_path.exists():
            failed = json.loads(failed_path.read_text())
            if (failed.get("identity") == identity and failed.get("patchLevel") == PATCH_LEVEL
                    and failed.get("helperSha256") == fingerprint
                    and failed.get("pairingMode", False) == pairing):
                raise ValueError(f"previous repair refused this AppImage: {failed['error']}")
        found = {"version": None}
        try:
            return build(app, state, identity, record, record_path, failed_path, found, pairing)
        except Exception as error:
            # Monitors read this file: it names the exact AppImage that runs unrepaired.
            write_json(failed_path, {"identity": identity, "patchLevel": PATCH_LEVEL,
                                     "pairingMode": pairing, "error": str(error), "at": now(),
                                     "appVersion": found["version"], "helperSha256": fingerprint})
            raise


def build(app, state, identity, record, record_path, failed_path, found, pairing=False):
    helper = (HERE / "power-recovery.js").read_text()
    current_sha = digest(app)
    build_app = app
    # A newer repair is rebuilt from the retained original, never by stacking
    # edits on top of a previously modified bundle.
    if record and current_sha == record.get("installedSha256"):
        build_app = Path(record["backup"])
        if digest(build_app) != record["originalSha256"]:
            raise ValueError("original AppImage backup verification failed")
    original_sha = digest(build_app)
    originals = state / "originals"
    originals.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".t3-recovery-", dir=app.parent) as work:
        work = Path(work)
        log = (state / "last-build.log").open("w")
        try:
            subprocess.run([str(build_app), "--appimage-extract"], cwd=work,
                           stdout=log, stderr=log, check=True)
            root = work / "squashfs-root"
            archive = root / "resources/app.asar"
            header, base = read_asar(archive)
            version = json.loads(read_member(archive, header, base, "package.json"))["version"]
            found["version"] = version
            name = restart_module(archive, header, base)
            codex = codex_module(archive, header, base, name)
            sessions = session_module(archive, header, base) if pairing else None
            originals_by_module = {module: read_member(archive, header, base, module).decode()
                                   for module in {name, codex, sessions} - {None}}
            if any(SESSION_MARKER in source for source in originals_by_module.values()):
                raise ValueError("already repaired AppImage without matching installation record")
            patched_by_module = dict(originals_by_module)
            if codex != name and CODEX_MARKER in originals_by_module[codex]:
                raise ValueError("already repaired AppImage without matching installation record")
            patched_by_module[name] = patch_bundle(patched_by_module[name], helper)
            if patched_by_module[name] == originals_by_module[name]:
                raise ValueError("already repaired AppImage without matching installation record")
            if codex != name:
                patched_by_module[codex] = patch_codex(patched_by_module[codex])
            if pairing:
                patched_by_module[sessions] = patch_sessions(patched_by_module[sessions])
            # Use the bundled Node runtime; no npm dependency or live T3 state.
            env = {**os.environ, "ELECTRON_RUN_AS_NODE": "1"}
            for index, (module, patched) in enumerate(sorted(patched_by_module.items())):
                syntax = work / f"check-{index}.mjs"
                syntax.write_text(patched)
                subprocess.run([str(root / "t3code"), "--check", str(syntax)], env=env,
                               stdout=log, stderr=log, check=True)
                rewrite_member(archive, module, patched.encode())
            check_header, check_base = read_asar(archive)
            for module, patched in patched_by_module.items():
                if read_member(archive, check_header, check_base, module) != patched.encode():
                    raise ValueError("ASAR verification failed")
            offset = int(subprocess.check_output([str(build_app), "--appimage-offset"], text=True).strip())
            squash = work / "root.squashfs"
            subprocess.run(["mksquashfs", str(root), str(squash), "-noappend", "-all-root",
                            "-comp", "zstd", "-processors", "2", "-no-progress"],
                           stdout=log, stderr=log, check=True)
            candidate = work / "T3-Code.AppImage"
            with build_app.open("rb") as original, candidate.open("wb") as target:
                prefix = original.read(offset)
                if len(prefix) != offset:
                    raise ValueError("invalid AppImage filesystem offset")
                target.write(prefix)
                with squash.open("rb") as filesystem:
                    shutil.copyfileobj(filesystem, target)
                target.flush()
                os.fsync(target.fileno())
            shutil.copymode(app, candidate)
            verification = work / "verify"
            verification.mkdir()
            subprocess.run([str(candidate), "--appimage-extract", "resources/app.asar"],
                           cwd=verification,
                           stdout=log, stderr=log, check=True)
            if digest(work / "verify/squashfs-root/resources/app.asar") != digest(archive):
                raise ValueError("repacked AppImage verification failed")
            if digest(app) != current_sha:
                raise ValueError("AppImage changed during repair; leaving the new download untouched")
            backup = originals / f"{original_sha}.AppImage"
            if not backup.exists():
                shutil.copy2(build_app, backup)
            if digest(backup) != original_sha:
                raise ValueError("original AppImage backup verification failed")
            repaired_sha = digest(candidate)
            candidate.replace(app)
            stamp = app.stat()
            record = {
                "patchLevel": PATCH_LEVEL, "version": version,
                "originalSha256": original_sha, "installedSha256": repaired_sha,
                "backup": str(backup), "installedAt": now(), "module": name, "codexModule": codex,
                "pairingMode": pairing, "sessionModule": sessions,
                "identity": [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns],
            }
            write_json(record_path, record)
            failed_path.unlink(missing_ok=True)
            prune_originals(originals, backup)
            return record
        finally:
            log.close()


PORT_RETRY_SECONDS = 600


def port_message(failed, checkout):
    return f"""The T3 Code AppImage on this PC updated to {failed.get('appVersion') or 'a new build'}, and the power-recovery repair refused it:

{failed.get('error')}

So T3 now runs without the repair: after a power cut, restart continuations do not wait for the internet. Port the repair to this build, unattended:

1. The helper is {checkout}/linux/power-recovery.py (with power-recovery.js); its tests are {checkout}/tests/test_power_recovery.py. Extract the current AppImage (~/Applications/T3-Code.AppImage --appimage-extract resources/app.asar, in a scratch folder) and find where the refused code went. Keep every older layout working; add the new one to the tests' layouts.
2. Run python3 -m unittest discover -s {checkout}/tests.
3. Install the two helper files into ~/.local/lib/t3code-power-recovery/ (as linux/install.sh does) and apply it: python3 ~/.local/lib/t3code-power-recovery/power-recovery.py. Then python3 ~/.local/lib/t3code-power-recovery/power-recovery.py --status must report "ok": true.
4. Commit in {checkout} and push it to every remote it has.

Do not restart or quit T3: the repaired AppImage takes effect at its next start, which is what a power cut causes. If the new code no longer has an equivalent of a step, stop and explain instead of guessing."""


def request_port(app, state):
    """A build this helper refuses: start one T3 thread on this machine that ports it.

    Once per refused build and helper version; retried every 10 minutes while T3 is not
    up yet (the watcher repairs before it launches T3). Needs the source checkout recorded
    at install time (`source` beside the helper) and the t3 command."""
    if (state / "no-auto-port").exists():
        return None
    try:
        failed = json.loads((state / "failed.json").read_text())
        stamp = app.stat()
    except (FileNotFoundError, ValueError):
        return None
    if failed.get("identity") != [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns]:
        return None
    request_path = state / "port-request.json"
    try:
        request = json.loads(request_path.read_text())
    except (FileNotFoundError, ValueError):
        request = {}
    same = request.get("identity") == failed["identity"] and request.get("helperSha256") == failed.get("helperSha256")
    if same and (request.get("thread") or time.time() - request.get("attemptedAt", 0) < PORT_RETRY_SECONDS):
        return request
    try:
        checkout = Path(os.environ.get("T3CODE_ANYWHERE_CHECKOUT") or (HERE / "source").read_text().strip())
    except FileNotFoundError:
        return None
    t3 = shutil.which("t3") or next((str(p) for p in (Path.home() / ".local/bin/t3", Path.home() / ".t3/bin/t3")
                                      if p.exists()), None)
    if not t3 or not (checkout / "linux/power-recovery.py").exists():
        return None
    request = {"identity": failed["identity"], "helperSha256": failed.get("helperSha256"),
               "appVersion": failed.get("appVersion"), "attemptedAt": time.time(), "thread": None}
    try:
        result = subprocess.run(
            [t3, "thread", "start", str(checkout), "-", "--json",
             "--title", f"Port T3 power recovery to {failed.get('appVersion') or 'the new build'}"],
            input=port_message(failed, checkout), capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            try:
                answer = json.loads(result.stdout)
                request["thread"] = answer.get("threadId") or answer.get("id") or result.stdout.strip()[:80]
            except ValueError:
                request["thread"] = result.stdout.strip()[:80]
            request["requestedAt"] = now()
        else:
            request["error"] = (result.stderr or result.stdout).strip()[-300:]
    except (OSError, subprocess.TimeoutExpired) as error:
        request["error"] = str(error)[:300]
    write_json(request_path, request)
    return request


def prune_originals(originals, keep):
    """Only the installed build's original is needed (a newer helper rebuilds from it)."""
    for path in originals.glob("*.AppImage"):
        if path != keep:
            path.unlink(missing_ok=True)


def status(app, state):
    """Read-only, quick: hashes the AppImage only when its identity changed."""
    result = {"app": str(app), "patchLevel": None, "currentAppMatches": False}
    try:
        result.update(json.loads((state / "installed.json").read_text()))
    except FileNotFoundError:
        pass
    try:
        stamp = app.stat()
    except FileNotFoundError:
        result.update(currentIdentity=None, failed=None, failedForCurrentApp=False, ok=False,
                      error="AppImage missing")
        return result
    identity = [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns]
    matches = "installedSha256" in result and (
        result.get("identity") == identity or digest(app) == result["installedSha256"])
    try:
        failed = json.loads((state / "failed.json").read_text())
    except FileNotFoundError:
        failed = None
    try:
        port = json.loads((state / "port-request.json").read_text())
    except (FileNotFoundError, ValueError):
        port = None
    result.update(currentIdentity=identity, currentAppMatches=matches, failed=failed,
                  failedForCurrentApp=failed is not None and failed.get("identity") == identity,
                  portRequest=port if port and port.get("identity") == identity else None,
                  ok=matches and result.get("patchLevel") == PATCH_LEVEL)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path.home() / "Applications/T3-Code.AppImage")
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/share/t3code-power-recovery")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--pairing-mode", choices=("on", "off"),
                        help="on: the next T3 start issues 100-year sessions to newly paired devices, "
                             f"for {PAIRING_MODE_HOURS} hours; off: back to the normal build. Restart T3 after each.")
    args = parser.parse_args()
    if args.pairing_mode:
        args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.pairing_mode == "on":
            (args.state / "pairing-mode").touch()
        else:
            (args.state / "pairing-mode").unlink(missing_ok=True)
    if args.status:
        print(json.dumps(status(args.app, args.state), indent=2))
        return
    try:
        print(json.dumps(apply(args.app.resolve(), args.state)))
    except ValueError:
        request_port(args.app.resolve(), args.state)
        raise


if __name__ == "__main__":
    main()
