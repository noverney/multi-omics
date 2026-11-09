"""Chaos run: break things while the labs deliver, then prove the result is identical.

Runs on the host (it drives `docker compose`; standard library only): `make chaos`.
Timeline: random task failures throughout, dispatcher down, flow-runner killed mid-batch,
one of three brokers stopped. Success = every file settles and the checksum of all derived
data equals the golden checksum of a clean run.
"""

import os
import subprocess
import sys
import time

LABS = ["sim-clinic", "sim-lab-a", "sim-lab-b", "sim-olink", "sim-rna", "sim-dna"]
ENV = {k: v for k, v in os.environ.items() if k != "DOCKER_DEFAULT_PLATFORM"}  # run native
TIMELINE = [  # (seconds after the labs start, what happens, compose arguments)
    (2, "analysis consumer DOWN: research falls behind, ingestion does not", ["stop", "analysis"]),
    (4, "dispatcher DOWN: upload events queue up in Redpanda", ["stop", "dispatcher"]),
    (10, "flow-runner KILLED (-9) mid-batch: a node crash", ["kill", "flow-runner"]),
    (14, "broker redpanda-1 DOWN: 2 of 3 replicas left", ["stop", "redpanda-1"]),
    (24, "dispatcher UP: resumes from its committed offset", ["start", "dispatcher"]),
    (32, "flow-runner UP: reconcile will re-run the files it dropped", ["start", "flow-runner"]),
    (50, "broker redpanda-1 UP: rejoins and re-syncs", ["start", "redpanda-1"]),
    (60, "analysis consumer UP: catches up from its committed offset", ["start", "analysis"]),
]
START = time.monotonic()


def say(message: str) -> None:
    """Print a timestamped line."""
    print(f"[t+{time.monotonic() - START:5.0f}s] {message}", flush=True)


def compose(*args: str, chaos: str | None = None, check: bool = True) -> str:
    """Run `docker compose <args>` natively; optionally set CHAOS_FAIL_RATE."""
    env = ENV | ({"CHAOS_FAIL_RATE": chaos} if chaos is not None else {})
    done = subprocess.run(["docker", "compose", *args], env=env, capture_output=True, text=True)
    if check and done.returncode:
        sys.exit(f"docker compose {' '.join(args)} failed:\n{done.stderr}")
    return done.stdout


def omics(*args: str, check: bool = True) -> str:
    """Run an omics CLI command in the tools container."""
    return compose("run", "--rm", "--no-deps", "tools", "python", "-m", "omics.cli", *args,
                   check=check)  # fmt: skip


def main() -> None:
    """Reset, deliver with chaos, wait for self-healing, compare with the golden checksum."""
    say("reset: wipe every topic, bucket, table and Prefect run")
    compose("--profile", "sim", "--profile", "tools", "down", "-v", "--remove-orphans")
    compose("up", "-d", "--wait", chaos="0.3")
    say("flow-runner runs with CHAOS_FAIL_RATE=0.3: random task crashes, retried by Prefect")
    compose("--profile", "sim", "up", "-d", "--force-recreate", *LABS)
    launch = time.monotonic()
    for at, what, args in TIMELINE:
        time.sleep(max(0.0, launch + at - time.monotonic()))
        say(what)
        compose(*args)
    say("waiting for every file to settle (reconcile runs every 60 s)...")
    omics("settle")
    retries = compose("logs", "flow-runner").count("Retry ")  # before the runner is replaced
    compose("up", "-d", "--no-deps", "flow-runner", chaos="0")
    say(f"settled. Prefect retried {retries} chaos-crashed tasks; files needing >1 attempt:")
    print(compose("exec", "-T", "postgres", "psql", "-U", "omics", "-d", "omics", "-tAc",
                  "SELECT string_agg(file_name || ' x' || attempts, ', ') FROM ops.ingest_file"
                  " WHERE attempts > 1"))  # fmt: skip
    result = omics("checksum", "--expect", "data/scenario/expected_checksum.txt", check=False)
    print(result)
    sys.exit(0 if "✅" in result else 1)


if __name__ == "__main__":
    main()
