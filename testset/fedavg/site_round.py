"""One round of a site in the plain FedAvg workflow (`wes/fedavg.py`, option C4).

Runs as the single executor of a TES task, with no network. Reads the current
global model and the site's data from the paths of the task's inputs, trains
the same logistic regression as the NVFlare job (`testset/job_src/client.py`,
same learning rate and local steps), and prints the update on one line:
`FEDAVG_UPDATE {"weights": [...], "rows": n}`. Only that line leaves the site,
through the task's record at the site's TES.

Usage: python3 site_round.py <model.json> <data.csv>
"""

import json
import pathlib
import sys

import numpy as np

# As in `testset/job_src/client.py`, so that both workflows train the same model
LEARNING_RATE = 0.5
LOCAL_STEPS = 20
MARKER = "FEDAVG_UPDATE "


def load(path: pathlib.Path) -> tuple[np.ndarray, np.ndarray]:
    """Load the data of the site.

    Args:
        path: Path of the CSV file with the columns x1, x2 and label.

    Returns:
        The features, with a bias column, and the labels.
    """
    rows = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    return np.column_stack([rows[:, :2], np.ones(len(rows))]), rows[:, 2]


def train(weights: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Run gradient descent on the local data.

    Args:
        weights: Weights to start from.
        x: Features.
        y: Labels.

    Returns:
        The updated weights.
    """
    for _ in range(LOCAL_STEPS):
        probabilities = 1.0 / (1.0 + np.exp(-x @ weights))
        weights = weights - LEARNING_RATE * x.T @ (probabilities - y) / len(y)
    return weights


def main() -> None:
    """Train from the global model on the local data, and print the update."""
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    model = np.asarray(json.loads(pathlib.Path(sys.argv[1]).read_text()), dtype=float)
    x, y = load(pathlib.Path(sys.argv[2]))
    weights = train(model, x, y)
    print(MARKER + json.dumps({"weights": weights.tolist(), "rows": len(y)}), flush=True)


if __name__ == "__main__":
    main()
