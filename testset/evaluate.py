"""Compare a federated model with models trained at one site alone.

Reads the synthetic data only: the holdout set and every share of a site
(`site-<k>.csv`) next to it. Prints the accuracy on the holdout set, and exits
with an error if the federated model doesn't beat every local model, also those
of shares that weren't in the run.
"""

import argparse
import pathlib
import sys

import numpy as np

LEARNING_RATE = 0.5
STEPS = 100


def load(path: pathlib.Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a CSV file of the data set.

    Args:
        path: Path of the file.

    Returns:
        The features, with a bias column, and the labels.
    """
    rows = np.loadtxt(path, delimiter=",", skiprows=1)
    return np.column_stack([rows[:, :2], np.ones(len(rows))]), rows[:, 2]


def fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Train a logistic regression with as many steps as the federated run.

    Args:
        x: Features.
        y: Labels.

    Returns:
        The weights.
    """
    weights = np.zeros(x.shape[1])
    for _ in range(STEPS):
        probabilities = 1.0 / (1.0 + np.exp(-x @ weights))
        weights = weights - LEARNING_RATE * x.T @ (probabilities - y) / len(y)
    return weights


def accuracy(weights: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    """Compute the accuracy of a model.

    Args:
        weights: Weights.
        x: Features.
        y: Labels.

    Returns:
        The share of correct predictions.
    """
    return float((((x @ weights) > 0) == y).mean())


def shares(data: pathlib.Path) -> list[pathlib.Path]:
    """Find the shares of the sites.

    Args:
        data: Directory of the data set.

    Returns:
        The files `site-<k>.csv`, by `k`.

    Raises:
        SystemExit: There are fewer than two.
    """
    found = sorted(
        (path for path in data.glob("site-*.csv") if path.stem.removeprefix("site-").isdigit()),
        key=lambda path: int(path.stem.removeprefix("site-")),
    )
    if len(found) < 2:
        sys.exit(f"Fewer than two shares (site-<k>.csv) in {data}")
    return found


def main() -> None:
    """Print the accuracies and check the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=pathlib.Path, help="Global model, a .npy file")
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path(__file__).parent / "data")
    parser.add_argument(
        "--expect",
        help="Accuracy of the federated model to expect, with three decimals as printed (testset/README.md)",
    )
    args = parser.parse_args()
    x, y = load(args.data / "holdout.csv")
    federated = accuracy(np.load(args.model).ravel(), x, y)
    local = {path.stem: accuracy(fit(*load(path)), x, y) for path in shares(args.data)}
    alone = ", ".join(f"{site} alone {value:.3f}" for site, value in local.items())
    print(f"holdout accuracy: federated {federated:.3f}, {alone}")
    if federated <= max(local.values()):
        sys.exit("The federated model doesn't beat the local ones")
    if args.expect is not None and f"{federated:.3f}" != args.expect:
        sys.exit(f"The federated model's accuracy isn't the expected {args.expect}")


if __name__ == "__main__":
    main()
