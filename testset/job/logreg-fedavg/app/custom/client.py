"""Local training of a site: logistic regression with plain NumPy.

Runs inside the FL client. Reads the site's CSV file from the path in the
environment variable `FL_DATA`; only model weights leave the site.
"""

import os

import numpy as np
import nvflare.client as flare
from nvflare.app_common.np.constants import NPConstants

LEARNING_RATE = 0.5
LOCAL_STEPS = 20


def load(path: str) -> tuple[np.ndarray, np.ndarray]:
    """Load the data of the site.

    Args:
        path: Path of the CSV file with the columns x1, x2 and label.

    Returns:
        The features, with a bias column, and the labels.
    """
    rows = np.loadtxt(path, delimiter=",", skiprows=1)
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
    """Receive the global model, train on local data, and send it back."""
    flare.init()
    site = flare.system_info()["site_name"]
    x, y = load(os.environ.get("FL_DATA", f"/data/{site}.csv"))
    print(f"{site}: {len(y)} local rows")
    while flare.is_running():
        model = flare.receive()
        weights = train(np.asarray(model.params[NPConstants.NUMPY_KEY], dtype=float), x, y)
        accuracy = float((((x @ weights) > 0) == y).mean())
        print(f"{site}: round {model.current_round}, local accuracy {accuracy:.3f}")
        flare.send(
            flare.FLModel(
                params={NPConstants.NUMPY_KEY: weights},
                params_type=flare.ParamsType.FULL,
                metrics={"accuracy": accuracy},
                current_round=model.current_round,
                meta={"NUM_STEPS_CURRENT_ROUND": LOCAL_STEPS},
            )
        )


if __name__ == "__main__":
    main()
