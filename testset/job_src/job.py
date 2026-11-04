"""Build the FLARE job and either run it in the simulator or export it."""

import argparse

from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe
from nvflare.recipe import SimEnv


def main() -> None:
    """Export the job, or run it in the simulator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-to", help="Directory to export the job to")
    parser.add_argument("--workspace", default="/tmp/fl-sim", help="Workspace of the simulator")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    recipe = NumpyFedAvgRecipe(
        name="logreg-fedavg",
        min_clients=2,
        num_rounds=args.rounds,
        model=[0.0, 0.0, 0.0],
        train_script="client.py",
    )
    if args.export_to:
        recipe.export(args.export_to)
        return
    run = recipe.execute(SimEnv(num_clients=2, workspace_root=args.workspace))
    print("Result:", run.get_result(), "Status:", run.get_status())


if __name__ == "__main__":
    main()
