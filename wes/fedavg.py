"""FedAvg as a plain workflow, without NVFlare: option C4 of `docs/testbed/options.md`. Sandbox only.

The second workflow type of the thin WES, `FEDAVG`. Each round is one TES task
per site, and nothing runs between rounds but this service. A site's task gets
the current model inline, as the `content` of an input, and its data by a URL
that only resolves at the site; it trains on that data, prints its update to
its output, and ends. The WES reads the update from the task's record (view
`FULL`), and averages the updates of the round, weighted by the sites' rows.

So no participant listens anywhere, and a task needs no network at all: no FL
port, no link to the hub, no token or key in a task record. What this costs in
privacy is in `docs/testbed/options.md` (C4) and `docs/testbed/shortcuts.md`
(H24).

Standard library only, so that its unit tests (`tests/fedavg_test.py`) run anywhere.
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

WORKFLOW_TYPE = "FEDAVG"
WORKFLOW_TYPE_VERSION = "1.0"
# As many rounds as the NVFlare job (`testset/job_src/job.py`), so that T1's holdout check applies
DEFAULT_ROUNDS = 5
MAX_ROUNDS = 20
# What a site's task prints before its update, on a line of its own
MARKER = "FEDAVG_UPDATE "
# An update line is a few hundred bytes; this bounds what a site can make the WES parse
MAX_LINE = 4096
# Only the end of a task's output is read: the update is the last thing a round prints
MAX_OUTPUT = 64 * 1024
MAX_ROWS = 10**9
# Far beyond any weight of the workloads here; keeps every weighted sum of updates finite
MAX_WEIGHT = 1e6
SCRIPT = "/app/testset/fedavg/site_round.py"
MODEL_PATH = "/model/model.json"


class Workload(NamedTuple):
    """A workload in the image: the script a site runs in a round, and the model to start from."""

    script: str
    initial: list[float]


# `workflow_url` names one of these: no uploads, so no user code (as H8 for NVFLARE)
WORKLOADS: dict[str, Workload] = {
    # The model of the NVFlare job `logreg-fedavg`: logistic regression on two features and a bias
    "logreg": Workload(SCRIPT, [0.0, 0.0, 0.0]),
}


class Update(NamedTuple):
    """A site's update: its weights after local training, and how many rows it trained on."""

    weights: list[float]
    rows: int


def parse_rounds(params: Mapping[str, Any]) -> int:
    """Read the number of rounds from a run's `workflow_params`.

    Args:
        params: The parameters.

    Returns:
        The number of rounds, `DEFAULT_ROUNDS` if none is given.

    Raises:
        ValueError: It isn't a whole number from 1 to `MAX_ROUNDS`.
    """
    rounds = params.get("rounds", DEFAULT_ROUNDS)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= MAX_ROUNDS:
        raise ValueError(f"rounds must be a whole number from 1 to {MAX_ROUNDS}")
    return rounds


def parse_timeout(value: str) -> float:
    """Read the setting `FEDAVG_ROUND_TIMEOUT`.

    Args:
        value: Its value.

    Returns:
        Seconds for all tasks of a round to end.

    Raises:
        ValueError: It isn't a finite number of seconds, 0 or more: a round
            would never time out, and hold the WES's one run forever.
    """
    try:
        seconds = float(value)
    except ValueError:
        seconds = math.nan
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("FEDAVG_ROUND_TIMEOUT must be a finite number of seconds, 0 or more")
    return seconds


def workload(name: str) -> Workload:
    """Look up a workload by the name a run gives as `workflow_url`.

    Args:
        name: The name.

    Returns:
        The workload.

    Raises:
        ValueError: There's no workload of that name.
    """
    if name not in WORKLOADS:
        raise ValueError(f"Unknown workload {name!r}; available: {sorted(WORKLOADS)}")
    return WORKLOADS[name]


def site_task(
    run_id: str, site: str, round_: int, model: Sequence[float], data_url: str, image: str, name: str
) -> dict[str, Any]:
    """Build the TES task of one site in one round.

    Args:
        run_id: Identifier of the run.
        site: Name of the site.
        round_: Number of the round, from 1.
        model: The current global model.
        data_url: URL of the site's data, which only resolves at the site.
        image: Image to run.
        name: Name of the workload.

    Returns:
        The task. The model is inline, so the task fetches nothing from the hub,
        and its record holds no token, link or address of the hub.
    """
    data_path = f"/data/{site}.csv"
    return {
        "name": f"fedavg-{site}-r{round_}-{run_id[:8]}",
        "description": "Round of a plain FedAvg WES run (sandbox)",
        "inputs": [
            {"name": "data", "url": data_url, "path": data_path, "type": "FILE"},
            {"name": "model", "content": json.dumps(list(model)), "path": MODEL_PATH, "type": "FILE"},
        ],
        "executors": [
            {
                "image": image,
                "command": ["python3", WORKLOADS[name].script, MODEL_PATH, data_path],
                "env": {"HOME": "/tmp"},
            }
        ],
        "resources": {"cpu_cores": 1, "ram_gb": 1.0, "disk_gb": 1.0},
        "tags": {"wes_run_id": run_id, "site": site, "round": str(round_)},
    }


def task_stdout(record: Mapping[str, Any]) -> str:
    """Get the output of a task, from its record in view `FULL`.

    Args:
        record: The record.

    Returns:
        The output of the last executor of the last attempt, or `""` if there's none.

    Raises:
        ValueError: The record isn't shaped as TES says, as from a TES that
            can't be trusted to be one.
    """
    if not isinstance(record, Mapping):
        raise ValueError("The task's record isn't an object")  # noqa: TRY004 - bad reply of a TES
    attempts = record.get("logs") or []
    if not isinstance(attempts, list) or not all(isinstance(attempt, Mapping) for attempt in attempts):
        raise ValueError("The task's logs aren't a list of attempts")
    executors = (attempts[-1].get("logs") or []) if attempts else []
    if not isinstance(executors, list) or not all(isinstance(executor, Mapping) for executor in executors):
        raise ValueError("The task's attempt doesn't list its executors")
    stdout = (executors[-1].get("stdout") or "") if executors else ""
    if not isinstance(stdout, str):
        raise ValueError("The task's output isn't text")  # noqa: TRY004 - bad reply of a TES
    return stdout


def _refuse_constant(name: str) -> None:
    """Refuse `NaN` and `Infinity` in an update, which Python's JSON parser takes by default.

    Args:
        name: The constant.

    Raises:
        ValueError: Always.
    """
    raise ValueError(f"not a finite number: {name}")


def parse_update(output: str, size: int) -> Update:
    """Read a site's update from its task's output.

    The output comes from the site, so it's checked before it gets anywhere
    near the average. Messages say what's wrong, and never echo the output.

    Args:
        output: The output of the task.
        size: Number of weights of the model.

    Returns:
        The update on the last line that starts with `MARKER`, within the last
        `MAX_OUTPUT` characters.

    Raises:
        ValueError: There's no such line, or it isn't an update for this model.
    """
    lines = [line for line in output[-MAX_OUTPUT:].splitlines() if line.startswith(MARKER)]
    if not lines:
        raise ValueError("The task printed no update")
    line = lines[-1][len(MARKER) :]
    if len(line) > MAX_LINE:
        raise ValueError("The update is too long")
    try:
        update = json.loads(line, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):  # RecursionError: nested too deeply, for some parsers
        raise ValueError("The update isn't valid JSON, or has a number that isn't finite") from None
    if not isinstance(update, dict):
        raise ValueError("The update isn't an object")  # noqa: TRY004 - bad output of a site, as all refusals here
    weights = update.get("weights")
    if not isinstance(weights, list) or len(weights) != size:
        raise ValueError(f"The update doesn't have {size} weights")
    values: list[float] = []
    for w in weights:
        if isinstance(w, bool) or not isinstance(w, int | float):
            raise ValueError("The weights aren't all numbers")  # noqa: TRY004 - bad output of a site
        try:
            value = float(w)
        except OverflowError:  # an integer too large for a float
            raise ValueError(f"The weights aren't all within ±{MAX_WEIGHT:g}") from None
        if not math.isfinite(value) or abs(value) > MAX_WEIGHT:
            raise ValueError(f"The weights aren't all within ±{MAX_WEIGHT:g}")
        values.append(value)
    rows = update.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= MAX_ROWS:
        raise ValueError(f"The update's rows aren't a whole number from 1 to {MAX_ROWS}")
    return Update(values, rows)


def aggregate(updates: Sequence[Update]) -> list[float]:
    """Average the updates of a round, weighted by the rows of each site (FedAvg).

    Args:
        updates: The updates, all of the same size.

    Returns:
        The new global model.

    Raises:
        ValueError: There are no updates, or the average isn't finite, which
            `parse_update`'s bounds rule out.
    """
    if not updates:
        raise ValueError("No updates to average")
    total = sum(update.rows for update in updates)
    model = [sum(update.weights[i] * update.rows for update in updates) / total for i in range(len(updates[0].weights))]
    if not all(math.isfinite(value) for value in model):
        raise ValueError("The average isn't finite")
    return model
