#!/usr/bin/env python3
"""Repair the desktop AppImage atomically; never open T3's state database.

Only exact, singly occurring bundle anchors are accepted. Original AppImages are
retained outside the checkout. A changed upstream layout is an error, not a best
effort binary edit. A mounted, running AppImage keeps its original inode.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

PATCH_LEVEL = 2
MARKER = "// t3code-anywhere power recovery v2"
HERE = Path(__file__).resolve().parent
OLD_CONTINUE_PROMPT = "Continue where you left off. Your last turn was cut short, so a command or other action it started may have finished or may still be running. Before you repeat one that changes state, confirm it did not take effect and is not still running; if you cannot tell, say so instead of repeating it."


def replace_one(source, old, new):
    count = source.count(old)
    if count != 1:
        raise ValueError(f"unsupported bundle: expected one {old[:100]!r}, found {count}")
    return source.replace(old, new, 1)


def patch_bundle(source, helper):
    if MARKER in source:
        return source
    source = replace_one(
        source,
        "yield* startNativeTurn(turnInput, turnInput.restartContinuationOfRunId === void 0 ? yield* toCodexInput(turnInput) : []);",
        'yield* startNativeTurn(turnInput, turnInput.restartContinuationOfRunId === void 0 ? yield* toCodexInput(turnInput) : [{ type: "text", text: "continue" }]);',
    )
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
    source = replace_one(
        source,
        "tapError$1(() => willRetry ? void_$1 : threads.recoverDelegatedTask(effect.threadId, sourceRunId))",
        'tapError$1((cause) => willRetry || t3RecoveryWaiting("provider-runtime.continue", cause) ? void_$1 : threads.recoverDelegatedTask(effect.threadId, sourceRunId))',
    )
    source = replace_one(
        source,
        "effect.attemptCount >= maxAttempts ? yield* outbox.fail({",
        "effect.attemptCount >= maxAttempts && !t3RecoveryWaiting(effect.request.type, error) ? yield* outbox.fail({",
    )
    source = replace_one(
        source,
        "delayMs: Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))",
        "delayMs: t3RecoveryWaiting(effect.request.type, error) ? 30_000 : Math.min(3e4, 100 * 2 ** Math.max(0, effect.attemptCount - 1))",
    )
    if "as tryPromise," not in source:
        raise ValueError("unsupported bundle: missing Effect.tryPromise import")
    return source


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
        record = None
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if record.get("identity") == identity and record.get("patchLevel") == PATCH_LEVEL:
                return record
        failed_path = state / "failed.json"
        if failed_path.exists():
            failed = json.loads(failed_path.read_text())
            if failed.get("identity") == identity and failed.get("patchLevel") == PATCH_LEVEL:
                raise ValueError(f"previous repair refused this AppImage: {failed['error']}")
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
                bundles = [name for name, _ in entries(header)
                           if name.startswith("apps/server/dist/binCli-") and name.endswith(".mjs")]
                if len(bundles) != 1:
                    raise ValueError("unsupported AppImage: expected one server CLI bundle")
                name = bundles[0]
                source = read_member(archive, header, base, name).decode()
                version = json.loads(read_member(archive, header, base, "package.json"))["version"]
                patched = patch_bundle(source, helper)
                if patched == source:
                    raise ValueError("already repaired AppImage without matching installation record")
                syntax = work / "check.mjs"
                syntax.write_text(patched)
                # Use the bundled Node runtime; no npm dependency or live T3 state.
                env = {**os.environ, "ELECTRON_RUN_AS_NODE": "1"}
                subprocess.run([str(root / "t3code"), "--check", str(syntax)], env=env,
                               stdout=log, stderr=log, check=True)
                rewrite_member(archive, name, patched.encode())
                check_header, check_base = read_asar(archive)
                if read_member(archive, check_header, check_base, name) != patched.encode():
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
                    "backup": str(backup), "installedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "identity": [stamp.st_ino, stamp.st_size, stamp.st_mtime_ns],
                }
                write_json(record_path, record)
                failed_path.unlink(missing_ok=True)
                return record
            except Exception as error:
                write_json(failed_path, {"identity": identity, "patchLevel": PATCH_LEVEL,
                                         "error": str(error)})
                raise
            finally:
                log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path.home() / "Applications/T3-Code.AppImage")
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/share/t3code-power-recovery")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        record = json.loads((args.state / "installed.json").read_text())
        record["currentAppMatches"] = digest(args.app) == record["installedSha256"]
        print(json.dumps(record, indent=2))
    else:
        print(json.dumps(apply(args.app.resolve(), args.state)))


if __name__ == "__main__":
    main()
