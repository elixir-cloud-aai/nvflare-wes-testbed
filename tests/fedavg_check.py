"""Check the WES's plain FedAvg runs (test T10) against a fake TES, with no network.

The fake TES answers in process, as `tes_request` would: it records the tasks
it gets, and ends each one as its scenario says, with what the task prints.
Checks that rounds chain (each round's tasks get the average of the last one),
that a failed task or a bad update ends the run as `EXECUTOR_ERROR` at once,
without echoing the output, and that a round that doesn't end in time fails
the run, and cancels its tasks.

A standalone script, run once per process: it changes globals of the WES.
"""

import json
import os
import pathlib
import sys
import tempfile
from collections.abc import Callable
from typing import Any
from unittest import mock

# Ends a task: its state, and what it printed, from the task and its number
Outcome = Callable[[dict[str, Any], int], tuple[str, str]]


class Reply:
    """What `requests` would return, as far as the WES reads it."""

    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        """Make a reply.

        Args:
            body: Its JSON body.
            status: Its status.
        """
        self.body = body
        self.status_code = status
        self.ok = status < 400

    def json(self) -> dict[str, Any]:
        """Get the body.

        Returns:
            The body.
        """
        return self.body

    def raise_for_status(self) -> None:
        """Raise on an error status, as `requests` does.

        Raises:
            RuntimeError: The status is an error.
        """
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTes:
    """A TES for all sites, that ends each task as `outcome` says."""

    def __init__(self, outcome: Outcome) -> None:
        """Start with no tasks.

        Args:
            outcome: How each task ends.
        """
        self.outcome = outcome
        self.tasks: list[dict[str, Any]] = []
        self.canceled: list[int] = []

    def request(self, method: str, site: str, url: str, **kwargs: Any) -> Reply:
        """Answer a request of the WES.

        Args:
            method: The HTTP method.
            site: Name of the site.
            url: The URL.
            **kwargs: The rest, as for `requests.request`.

        Returns:
            The reply.
        """
        if method == "POST" and url.endswith("/tasks"):
            self.tasks.append(kwargs["json"])
            return Reply({"id": str(len(self.tasks) - 1)})
        number = int(url.rsplit("/", 1)[1].split(":")[0])
        if url.endswith(":cancel"):
            self.canceled.append(number)
            return Reply({})
        state, stdout = self.outcome(self.tasks[number], number)
        if number in self.canceled and state == "RUNNING":
            state = "CANCELED"
        return Reply({"id": str(number), "state": state, "logs": [{"logs": [{"stdout": stdout}]}]})


def model_of(task: dict[str, Any]) -> list[float]:
    """Get the model a task got.

    Args:
        task: The task.

    Returns:
        The model, from its inline input.
    """
    return json.loads(next(entry["content"] for entry in task["inputs"] if entry["name"] == "model"))


def update(weights: list[float], rows: int) -> str:
    """Print an update, as a site's task does.

    Args:
        weights: The weights.
        rows: The rows.

    Returns:
        The output.
    """
    return "local training done\nFEDAVG_UPDATE " + json.dumps({"weights": weights, "rows": rows}) + "\n"


def run(wes: Any, outcome: Outcome, rounds: int = 2) -> tuple[dict[str, Any], FakeTes]:
    """Carry out one FedAvg run of two sites against a fake TES.

    Args:
        wes: The WES module.
        outcome: How each task ends.
        rounds: Number of rounds.

    Returns:
        The run, and the fake TES.
    """
    tes = FakeTes(outcome)
    run_id = f"run-{len(wes.RUNS)}"
    wes.RUNS[run_id] = {"state": "QUEUED", "tasks": [], "outputs": {}}
    with mock.patch.object(wes, "tes_request", tes.request), mock.patch.object(wes.time, "sleep", lambda _: None):
        wes.execute_fedavg(run_id, "logreg", ["site-1", "site-2"], rounds)
    return wes.RUNS[run_id], tes


def main() -> None:
    """Run the scenarios, and check what came out."""
    with tempfile.TemporaryDirectory() as directory:
        os.environ["WES_WORKDIR"] = directory
        os.environ["FL_PROBE_RESPONDER"] = "0"
        os.environ["WES_SITES"] = json.dumps(
            {
                "site-1": {"tes": "http://tes-1.invalid", "data": "file:///data/site-1.csv"},
                "site-2": {"tes": "http://tes-2.invalid", "data": "file:///data/site-2.csv"},
            }
        )
        sys.path.insert(0, "/app")
        import numpy as np

        from wes import app as wes

        # Site 1 adds 1 to each weight, site 2 adds 3 and has three times the rows: the average adds 2.5
        def trains(task: dict[str, Any], _number: int) -> tuple[str, str]:
            model = model_of(task)
            step, rows = (1.0, 10) if task["tags"]["site"] == "site-1" else (3.0, 30)
            return "COMPLETE", update([w + step for w in model], rows)

        good, good_tes = run(wes, trains, rounds=3)
        model_path = pathlib.Path(directory) / "run-0" / "global_model.npy"
        model = np.load(model_path).tolist() if model_path.is_file() else None

        def fails(task: dict[str, Any], _number: int) -> tuple[str, str]:
            if task["tags"]["site"] == "site-1":
                return "EXECUTOR_ERROR", ""
            return "RUNNING", ""

        failed, failed_tes = run(wes, fails)

        def lies(task: dict[str, Any], _number: int) -> tuple[str, str]:
            if task["tags"]["site"] == "site-2":
                return "COMPLETE", "FEDAVG_UPDATE " + json.dumps({"weights": ["decoy-output"], "rows": 1})
            return trains(task, _number)

        bad, _ = run(wes, lies)

        wes.ROUND_TIMEOUT = 0
        stuck, stuck_tes = run(wes, lambda _task, _number: ("RUNNING", ""))

    rounds = [[model_of(task) for task in good_tes.tasks[i : i + 2]] for i in range(0, 6, 2)]
    checks = {
        "a good run is COMPLETE": good["state"] == "COMPLETE",
        "one task per site and round": len(good["tasks"]) == 6
        and [(t["site"], t["round"]) for t in good["tasks"]]
        == [(site, r) for r in (1, 2, 3) for site in ("site-1", "site-2")],
        "round 1 starts from the workload's model": rounds[0] == [[0.0, 0.0, 0.0]] * 2,
        "each round gets the average of the last, weighted by rows": rounds[1] == [[2.5] * 3] * 2
        and rounds[2] == [[5.0] * 3] * 2,
        "the global model is the last average": model == [7.5] * 3,
        "the run names its rounds and model": good["outputs"].get("rounds_completed") == 3
        and good["outputs"].get("global_model", "").endswith("/global_model.npy"),
        "no task record holds a link or a token": all(
            "token" not in json.dumps(task).lower() and json.dumps(task).count("://") == 1 for task in good_tes.tasks
        ),
        "a failed task ends the run as EXECUTOR_ERROR": failed["state"] == "EXECUTOR_ERROR",
        "the error names the site": "site-1" in failed.get("error", ""),
        "no next round after a failed task": len(failed_tes.tasks) == 2,
        "the other task of the round is canceled": failed_tes.canceled == [1],
        "a bad update ends the run as EXECUTOR_ERROR": bad["state"] == "EXECUTOR_ERROR",
        "the error names the site, not the output": "site-2" in bad.get("error", "")
        and "decoy-output" not in bad.get("error", ""),
        "a failed run has no model": "global_model" not in failed["outputs"] and "global_model" not in bad["outputs"],
        "a round that doesn't end in time fails the run": stuck["state"] == "SYSTEM_ERROR"
        and "in time" in stuck.get("error", ""),
        "its tasks are canceled": sorted(stuck_tes.canceled) == [0, 1],
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    failed_checks = [name for name, passed in checks.items() if not passed]
    print(f"{len(checks) - len(failed_checks)}/{len(checks)} checks passed")
    sys.exit(1 if failed_checks else 0)


if __name__ == "__main__":
    main()
