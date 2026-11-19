"""Check the comparison with local models (`testset/evaluate.py`) and the names of the jobs, with no network.

Runs in the image, which has NumPy and NVFlare: `evaluate.py` finds the shares
of the sites by number, needs two of them, and with `--expect` fails on any
other federated accuracy; `job.py` names the job of two sites as before, and
the others by their number of sites.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

EVALUATE = "/app/testset/evaluate.py"
# What FedAvg of NVFlare 2.9 takes when a job's config leaves `num_clients` out
FEDAVG_DEFAULT_NUM_CLIENTS = 3


def load_module(name: str, path: str) -> Any:
    """Load a script of the image as a module.

    Args:
        name: Name to give it.
        path: Its path.

    Returns:
        The module.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: pathlib.Path, x2_low: float, x2_high: float, rng: np.random.Generator) -> None:
    """Write a share of rows with a label from the rule of the test set.

    Args:
        path: File to write.
        x2_low: Lower bound of the feature x2.
        x2_high: Upper bound of the feature x2.
        rng: Random number generator.
    """
    x1 = rng.uniform(-2.0, 2.0, 40)
    x2 = rng.uniform(x2_low, x2_high, 40)
    rows = np.column_stack([x1, x2, (2 * x1 - 3 * x2 + 0.5 > 0).astype(float)])
    np.savetxt(path, rows, delimiter=",", header="x1,x2,label", comments="", fmt=["%.4f", "%.4f", "%d"])


def evaluate(model: pathlib.Path, data: pathlib.Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run `evaluate.py`.

    Args:
        model: The model.
        data: Directory of the data.
        *extra: More arguments.

    Returns:
        What it did.
    """
    return subprocess.run(
        [sys.executable, EVALUATE, str(model), "--data", str(data), *extra], capture_output=True, text=True, check=False
    )


def num_clients(job_dir: pathlib.Path) -> tuple[int, int]:
    """Read how many sites a job takes, and how many its FedAvg asks each round.

    Args:
        job_dir: Directory of the job.

    Returns:
        `min_clients` of the job, and `num_clients` of its FedAvg.
    """
    meta = json.loads((job_dir / "meta.json").read_text())
    server = json.loads((job_dir / "app" / "config" / "config_fed_server.json").read_text())
    (workflow,) = [w for w in server["workflows"] if w["path"].endswith(".FedAvg")]
    asked = workflow["args"].get("num_clients", FEDAVG_DEFAULT_NUM_CLIENTS)
    return meta["min_clients"], asked


def main() -> None:
    """Run the cases, and check what came out."""
    evaluate_module = load_module("evaluate", EVALUATE)
    job = load_module("job", "/app/testset/job_src/job.py")
    rng = np.random.default_rng(0)
    with tempfile.TemporaryDirectory() as directory:
        data = pathlib.Path(directory)
        write(data / "holdout.csv", -2.0, 2.0, rng)
        write(data / "site-1.csv", -2.0, -0.2, rng)
        model = data / "model.npy"
        # The rule itself: right on every row without noise
        np.save(model, np.array([2.0, -3.0, 0.5]))
        one_share = evaluate(model, data)
        for k, (low, high) in {2: (0.2, 2.0), 10: (-2.0, -1.0)}.items():
            write(data / f"site-{k}.csv", low, high, rng)
        (data / "site-x.csv").write_text("not a share\n")
        found = [path.name for path in evaluate_module.shares(data)]
        good = evaluate(model, data, "--expect", "1.000")
        other = evaluate(model, data, "--expect", "0.975")
        np.save(model, np.zeros(3))
        bad = evaluate(model, data)

    checks = {
        "one share is refused": one_share.returncode != 0 and "Fewer than two shares" in one_share.stderr,
        "shares are found by number, others ignored": found == ["site-1.csv", "site-2.csv", "site-10.csv"],
        "every share is compared": "site-10 alone" in good.stdout,
        "the expected accuracy passes": good.returncode == 0,
        "another expected accuracy fails": other.returncode != 0 and "expected 0.975" in other.stderr,
        "a model that doesn't beat the local ones fails": bad.returncode != 0,
        "the job of two sites keeps its name": job.job_name(2) == "logreg-fedavg",
        "the jobs of more sites are named by their number": [job.job_name(n) for n in (3, 4)]
        == ["logreg-fedavg-3", "logreg-fedavg-4"],
        "a job of each name is in the image": all(
            (pathlib.Path("/app/testset/job") / job.job_name(n) / "meta.json").is_file() for n in (2, 3, 4)
        ),
        # The WES checks `min_clients`; FedAvg asks `num_clients` each round: they must agree
        "each job's FedAvg asks all its sites each round": all(
            num_clients(pathlib.Path("/app/testset/job") / job.job_name(n)) == (n, n) for n in (2, 3, 4)
        ),
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    failed = [name for name, passed in checks.items() if not passed]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
