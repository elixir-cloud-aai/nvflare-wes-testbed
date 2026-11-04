"""Generate the tiny synthetic data set of the testbed.

Everything here is made up: two features drawn from a seeded random number
generator and a label from a fixed linear rule, with some noise. It describes
nothing and nobody.

The two sites see different parts of the feature space (a non-IID split), so
that a model trained at one site alone generalizes badly and federated
averaging has something to show.
"""

import argparse
import pathlib

import numpy as np

SEED = 20261104
WEIGHTS = np.array([2.0, -3.0])
BIAS = 0.5
NOISE = 0.25


def sample(rng: np.random.Generator, n: int, x2_low: float, x2_high: float) -> np.ndarray:
    """Draw rows of the data set.

    Args:
        rng: Random number generator.
        n: Number of rows.
        x2_low: Lower bound of the feature x2.
        x2_high: Upper bound of the feature x2.

    Returns:
        Array with the columns x1, x2 and label.
    """
    x1 = rng.uniform(-2.0, 2.0, n)
    x2 = rng.uniform(x2_low, x2_high, n)
    scores = WEIGHTS[0] * x1 + WEIGHTS[1] * x2 + BIAS + rng.normal(0.0, NOISE, n)
    return np.column_stack([x1, x2, (scores > 0).astype(float)])


def write(path: pathlib.Path, rows: np.ndarray) -> None:
    """Write rows as a CSV file.

    Args:
        path: File to write.
        rows: Rows to write.
    """
    np.savetxt(path, rows, delimiter=",", header="x1,x2,label", comments="", fmt=["%.4f", "%.4f", "%d"])


def main() -> None:
    """Write the files of both sites and the holdout set."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path(__file__).parent / "data")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    write(out / "site-1.csv", sample(rng, 40, -2.0, -0.2))
    write(out / "site-2.csv", sample(rng, 40, 0.2, 2.0))
    write(out / "holdout.csv", sample(rng, 40, -2.0, 2.0))


if __name__ == "__main__":
    main()
