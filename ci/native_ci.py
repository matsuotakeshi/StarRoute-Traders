#!/usr/bin/env python3
"""Run unchanged native suites concurrently through the existing CI SSH keys."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import threading
import time

from native_remote import RESULT

ROOT = Path(__file__).resolve().parents[1]
LINER_SHA = "ad20f564955bb97e43addac3c4f18e79c7eef62c"
TARGETS = {
    "freebsd": ("takeshi@10.0.0.50", "/home/ci/.ssh/id_ed25519_freebsd_ci"),
    "rocky": ("ci-test@10.0.0.51", "/home/ci/.ssh/id_ed25519_rocky_ci"),
    "ubuntu": ("ci-test@10.0.0.53", "/home/ci/.ssh/id_ed25519_ubuntu_ci"),
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def require_trusted_main(env, sha, head):
    if (env.get("GITHUB_REF") != "refs/heads/main"
            or env.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch")
            or env.get("GITHUB_REPOSITORY") != "matsuotakeshi/StarRoute-Traders"
            or not re.fullmatch(r"[0-9a-f]{40}", sha) or sha != head
            or env.get("GITHUB_SHA") != sha):
        raise ValueError("Native SSH is allowed only for the exact trusted main checkout")


def ssh_options(key):
    return ["-i", key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "PasswordAuthentication=no", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=3"]


def run_setup(command, log, cancelled, capture=False):
    if cancelled.is_set():
        raise RuntimeError("Run cancelled before source transfer")
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else log, stderr=log, timeout=60)
    if result.returncode:
        raise RuntimeError("Source transfer/setup failed: " + str(result.returncode))
    return result.stdout.decode("utf8").strip() if capture else None


def supervise(command, log, cancelled, timeout=3400):
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log,
                               start_new_session=True)
    deadline = time.monotonic() + timeout
    next_heartbeat = 0.0
    try:
        while process.poll() is None:
            if cancelled.is_set():
                raise RuntimeError("Run cancelled")
            if time.monotonic() >= deadline:
                raise RuntimeError("SSH suite timed out")
            if time.monotonic() >= next_heartbeat:
                try:
                    process.stdin.write(b"alive\n")
                    process.stdin.flush()
                except BrokenPipeError:
                    return process.wait(timeout=15)
                next_heartbeat = time.monotonic() + 5
            time.sleep(0.2)
        return process.returncode
    finally:
        # Closing stdin tells the remote supervisor to reap the build group.
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            # A network failure also expires the remote heartbeat lease.


def parse_result(log_path, target, sha):
    records = []
    for line in log_path.read_text(encoding="utf8", errors="replace").splitlines():
        if line.startswith(RESULT):
            records.append(json.loads(line[len(RESULT):]))
    if len(records) != 1 or records[0].get("target") != target or records[0].get("source_sha") != sha:
        raise ValueError("Missing, duplicate or mismatched native result")
    if records[0].get("status") != "passed":
        raise RuntimeError(records[0].get("error", "Native suite failed"))
    return records[0]


def execute_target(target, archive, digest, sha, output, cancelled, fixture, fixture_digest):
    started = time.monotonic()
    result = {"target": target, "source_sha": sha, "archive_sha256": digest,
              "status": "failed", "started_at": timestamp()}
    host, key = TARGETS[target]
    ssh = ["ssh", *ssh_options(key), host]
    log_path = output / (target + ".log")
    print(target + ": starting native CI", flush=True)
    directory = None
    unpacked = False
    with log_path.open("wb") as log:
        try:
            if not Path(key).is_file():
                raise ValueError("Configured CI SSH key is unavailable")
            directory = run_setup(ssh + [
                'umask 077; mkdir -p "$HOME/ci/starroute" && mktemp -d "$HOME/ci/starroute/run-' + target + '-XXXXXXXX"'
            ], log, cancelled, capture=True)
            if not re.fullmatch(r"/[A-Za-z0-9_./-]+/ci/starroute/run-" + target + r"-[A-Za-z0-9]+", directory) or ".." in directory.split("/"):
                raise ValueError("Unexpected remote directory")
            result["remote_directory"] = directory
            run_setup(["scp", *ssh_options(key), str(archive), host + ":" + directory + "/source.tar.gz"], log, cancelled)
            bootstrap = (ROOT / "ci/native_remote.py").read_text(encoding="utf8")
            # Single-line command works with existing sh/csh login shells alike.
            encoded = base64.b64encode(bootstrap.encode("utf8")).decode("ascii")
            loader = 'import base64;exec(base64.b64decode("' + encoded + '"))'
            run_setup(ssh + [shlex.join(["python3", "-c", loader, "unpack", directory, digest, sha])], log, cancelled)
            unpacked = True
            fixture_dir = directory + "/liner-fixture"
            run_setup(ssh + ["mkdir " + shlex.quote(fixture_dir)], log, cancelled)
            run_setup(["scp", *ssh_options(key), str(fixture), host + ":" + fixture_dir + "/source.tar.gz"], log, cancelled)
            run_setup(ssh + [shlex.join(["python3", "-c", loader, "unpack", fixture_dir, fixture_digest, LINER_SHA])], log, cancelled)
            command = "cd " + shlex.quote(directory + "/source") + " && exec " + shlex.join([
                "python3", "ci/native_remote.py", "worker", target, sha])
            result["tests_started_at"] = timestamp()
            code = supervise(ssh + [command], log, cancelled)
            result["tests_finished_at"] = timestamp()
            log.flush()
            if code:
                raise RuntimeError("Native SSH exited with status " + str(code))
            record = parse_result(log_path, target, sha)
            result["tests"] = record["tests"]
            result["liner_fixture_sha"] = LINER_SHA
            run_setup(["scp", *ssh_options(key), host+":"+directory+"/door-demo/result.json", str(output/(target+"-door.json"))], log, cancelled)
            result["status"] = "passed"
        except Exception as error:
            result["status"] = "cancelled" if cancelled.is_set() else "failed"
            result["error"] = str(error)
            log.write(("\nCI_ERROR " + str(error) + "\n").encode("utf8"))
        finally:
            if unpacked:
                try:
                    run_setup(ssh + [shlex.join(["python3", "-c", loader, "cleanup", directory, sha])], log, threading.Event())
                    result["cleanup"] = "removed-own-run"
                except Exception as error:
                    result["cleanup"] = "deferred: "+str(error)
                    result["status"] = "failed"

    result.update(finished_at=timestamp(), duration_seconds=round(time.monotonic() - started, 3))
    print(target + ": " + result["status"] + " (" + str(result["duration_seconds"]) + "s)", flush=True)
    return result


def run_parallel(targets, task):
    results = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {pool.submit(task, target): target for target in targets}
        for future in as_completed(futures):
            target = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                results.append({"target": target, "status": "failed", "error": str(error)})
    return sorted(results, key=lambda row: row["target"])


def all_passed(results, targets, sha):
    return (len(results) == len(targets) and {r.get("target") for r in results} == set(targets)
            and all(r.get("status") == "passed" and r.get("source_sha") == sha for r in results))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["all", *TARGETS], default="all")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sha = os.environ.get("GITHUB_SHA", "")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    from runner_admission import allowed
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if sha != head or not allowed(os.environ,event):
        raise ValueError('Native checkout or trusted event mismatch')
    if subprocess.check_output(["git", "diff", "HEAD", "--", "ci/native_ci.py", "ci/native_remote.py"], cwd=ROOT):
        raise ValueError("Native supervisor differs from committed source")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source.tar.gz"
    subprocess.run(["git", "archive", "--format=tar.gz", "--output=" + str(archive), sha], cwd=ROOT, check=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    fixture_repo = output / "liner-checkout"
    subprocess.run(["git","init",str(fixture_repo)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git","-C",str(fixture_repo),"fetch","--depth=1","https://github.com/matsuotakeshi/liner-notes.git",LINER_SHA], check=True)
    fixture = output/"liner.tar.gz"
    subprocess.run(["git","-C",str(fixture_repo),"archive","--format=tar.gz","--output="+str(fixture),LINER_SHA], check=True)
    fixture_digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    cancelled = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda signum, frame: cancelled.set())
    targets = list(TARGETS) if args.target == "all" else [args.target]
    started = time.monotonic()
    results = run_parallel(targets, lambda target: execute_target(target, archive, digest, sha, output, cancelled, fixture, fixture_digest))
    ok = all_passed(results, targets, sha) and not cancelled.is_set()
    report = {"source_sha": sha, "archive_sha256": digest, "ok": ok,
              "liner_fixture_sha": LINER_SHA, "targets": targets, "duration_seconds": round(time.monotonic() - started, 3), "results": results}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf8") as stream:
            stream.write("## Native CI: " + sha + "\n\n| OS | Result | Tests | Python | Seconds |\n| --- | --- | --- | --- | --- |\n")
            for row in results:
                stream.write("| " + row["target"] + " | " + row["status"] + " | " + str(row.get("tests",{}).get("tests","-"))+" | "+str(row.get("tests",{}).get("environment",{}).get("python","-")).split(" ")[0]+" | "+str(row.get("duration_seconds", "-")) + " |\n")
            stream.write("\nParallel wall time: " + str(report["duration_seconds"]) + " seconds.\n")
    print(json.dumps(report), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
