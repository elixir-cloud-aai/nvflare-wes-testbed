"""Compare a federated model with models trained at one site alone.

Reads the synthetic data only. Prints the accuracy on the holdout set, and
exits with an error if the federated model doesn't beat both local models.
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


def main() -> None:
    """Print the three accuracies and check the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=pathlib.Path, help="Global model, a .npy file")
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path(__file__).parent / "data")
    args = parser.parse_args()
    x, y = load(args.data / "holdout.csv")
    federated = accuracy(np.load(args.model).ravel(), x, y)
    local = {site: accuracy(fit(*load(args.data / f"{site}.csv")), x, y) for site in ("site-1", "site-2")}
    print(
        f"holdout accuracy: federated {federated:.3f}, site-1 alone {local['site-1']:.3f}, site-2 alone {local['site-2']:.3f}"
    )
    if federated <= max(local.values()):
        sys.exit("The federated model doesn't beat the local ones")


if __name__ == "__main__":
    main()
