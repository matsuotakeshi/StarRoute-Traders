#!/usr/bin/env python3
"""Trusted native CI worker; standard-library only on FreeBSD and Linux."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import select
import signal
import subprocess
import sys
import tarfile
import time

RESULT = "SRT_NATIVE_RESULT "


def unpack(directory, digest, sha):
    directory = Path(directory)
    archive = directory / "source.tar.gz"
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()
    if actual != digest or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Source archive checksum or commit is invalid")
    destination = directory / "source"
    destination.mkdir(mode=0o700)  # A new run must never overwrite an old one.
    if archive.stat().st_size > 100*1024*1024:
        raise ValueError("Source archive exceeds size limit")
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            total += member.size
            if total > 300*1024*1024:
                raise ValueError("Expanded source exceeds size limit")
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isdir() or member.isfile()):
                raise ValueError("Unsafe source archive member: " + member.name)
            target = destination.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                target.chmod(member.mode & 0o777)
    (destination / ".ci-source-sha").write_text(sha + "\n", encoding="ascii")


def commands_for(target):
    python = sys.executable
    liner = str(Path.cwd().parent / "liner-fixture" / "source")
    flags = [] if target == "freebsd" else ["CC=clang", "SQLITE_CFLAGS=", "SQLITE_LIBS=-lsqlite3"]
    return [[python, "ci/run_tests.py", "--output", "ci-output"],
            ["make", "-C", liner, "-j2", *flags, "runtime"],
            [python, "scripts/bbs_ui_telnet_demo.py", "--directory", str(Path.cwd().parent / "door-demo"), "--liner", liner]]


def verify_os(target):
    if target == "freebsd":
        if platform.system() != "FreeBSD":
            raise ValueError("Expected FreeBSD")
    else:
        values = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
        if platform.system() != "Linux" or values.get("ID", "").strip('"') != target:
            raise ValueError("Unexpected Linux distribution")


def stop_group(process):
    """Reap the build command and its process group, including stubborn children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def heartbeat(heartbeat_fd, state, lease, stopped):
    if stopped():
        raise RuntimeError("Worker cancelled")
    ready, _, _ = select.select([heartbeat_fd], [], [], 0.2)
    if ready:
        message = os.read(heartbeat_fd, 4096)
        if not message:
            raise RuntimeError("Runner disconnected")
        state['pending'] += message
        while b'\n' in state['pending']:
            line, state['pending'] = state['pending'].split(b'\n', 1)
            if line != b'alive':
                raise RuntimeError("Invalid runner heartbeat")
            state['last'] = time.monotonic()
        if len(state['pending']) > 32:
            raise RuntimeError("Invalid runner heartbeat")
    if time.monotonic() - state['last'] > lease:
        raise RuntimeError("Runner heartbeat expired")


def run_commands(commands, heartbeat_fd, timeout=3300, lease=45, stopped=lambda: False, heartbeat_state=None):
    """EOF, lost heartbeat, cancellation and timeouts all fail closed."""
    deadline = time.monotonic() + timeout
    state = heartbeat_state if heartbeat_state is not None else {'last': time.monotonic(), 'pending': b''}
    env = dict(os.environ, LINER_TEST_START_TIMEOUT="180", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    for command in commands:
        print("NATIVE_STEP " + json.dumps(command), flush=True)
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        try:
            while True:
                now = time.monotonic()
                if stopped():
                    raise RuntimeError("Worker cancelled")
                if now >= deadline:
                    raise RuntimeError("Native suite timed out")
                heartbeat(heartbeat_fd, state, lease, stopped)
                code = process.poll()
                if code is not None:
                    if code != 0:
                        raise RuntimeError("Build/test command failed: " + str(code))
                    break
        except BaseException:
            stop_group(process)
            raise


@contextmanager
def host_lock(path, heartbeat_fd=None, timeout=1200, lease=45, stopped=lambda: False):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        state = {'last': time.monotonic(), 'pending': b''}
        deadline = time.monotonic() + timeout
        while True:
            if stopped():
                raise RuntimeError("Worker cancelled")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if heartbeat_fd is None:
                    raise  # Preserve the original fail-fast interface.
                if time.monotonic() >= deadline:
                    raise RuntimeError("Native host lock wait timed out")
                heartbeat(heartbeat_fd, state, lease, stopped)
        yield state


def worker(target, sha, timeout, lease):
    if (Path.cwd() / ".ci-source-sha").read_text(encoding="ascii").strip() != sha:
        raise ValueError("Extracted source commit differs")
    verify_os(target)
    lock_path = Path.home() / "ci" / ".liner-notes-native.lock"
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, cancel)
    deadline = time.monotonic() + timeout
    with host_lock(Path.cwd().parent / ".worker.lock"), host_lock(lock_path, sys.stdin.fileno(), min(1200, timeout), lease, lambda: cancelled) as state:
        # All single-OS and parallel entry points share this per-host lock.
        print(platform.platform(), flush=True)
        if target != "freebsd":
            print(Path("/etc/os-release").read_text(), flush=True)
            for command in (["python3", "--version"], ["clang", "--version"], ["free", "-h"]):
                subprocess.run(command, check=True, timeout=15)
        run_commands(commands_for(target), sys.stdin.fileno(), max(0, deadline-time.monotonic()), lease, lambda: cancelled, state)


def cleanup(directory, sha):
    import shutil
    directory = directory.resolve()
    if directory.parent != (Path.home()/"ci"/"starroute").resolve() or not re.fullmatch(r"run-(freebsd|rocky|ubuntu)-[A-Za-z0-9]+", directory.name):
        raise ValueError("Cleanup path outside StarRoute runs")
    marker=directory/"source"/".ci-source-sha"
    if marker.read_text().strip()!=sha:
        raise ValueError("Cleanup commit mismatch")
    with host_lock(directory/".worker.lock"):
        shutil.rmtree(directory)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    bootstrap = sub.add_parser("unpack")
    bootstrap.add_argument("directory")
    bootstrap.add_argument("digest")
    bootstrap.add_argument("sha")
    clean = sub.add_parser("cleanup")
    clean.add_argument("directory")
    clean.add_argument("sha")
    run = sub.add_parser("worker")
    run.add_argument("target", choices=["freebsd", "rocky", "ubuntu"])
    run.add_argument("sha")
    run.add_argument("--timeout", type=int, default=3300)
    run.add_argument("--lease", type=int, default=45)
    args = parser.parse_args()
    if args.mode == "cleanup":
        cleanup(Path(args.directory), args.sha)
        return 0
    if args.mode == "unpack":
        unpack(args.directory, args.digest, args.sha)
        return 0
    result = {"target": args.target, "source_sha": args.sha, "status": "failed"}
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.sha) or not 1 <= args.lease <= 300 or not 1 <= args.timeout <= 3300:
            raise ValueError("Invalid worker limits or commit")
        try:
            worker(args.target, args.sha, args.timeout, args.lease)
        finally:
            report = Path("ci-output/tests.json")
            if report.exists():
                result["tests"] = json.loads(report.read_text())
        result["status"] = "passed"
    except Exception as error:
        result["error"] = str(error)
    print(RESULT + json.dumps(result), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
