"""Build the FLARE job and either run it in the simulator or export it.

The job takes exactly as many sites as it is built for: FedAvg of NVFlare 2.9
asks a random subset of `num_clients` of the connected clients each round, so a
job for two sites would leave a third site out of some rounds. Hence one job
per number of sites: `logreg-fedavg` for two, `logreg-fedavg-<n>` for more.
"""

import argparse

from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe
from nvflare.recipe import SimEnv


def job_name(sites: int) -> str:
    """Name the job for a number of sites.

    Args:
        sites: Number of sites.

    Returns:
        `logreg-fedavg` for two sites, the name of the job before there were
        more, and `logreg-fedavg-<sites>` otherwise.
    """
    return "logreg-fedavg" if sites == 2 else f"logreg-fedavg-{sites}"


def main() -> None:
    """Export the job, or run it in the simulator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-to", help="Directory to export the job to")
    parser.add_argument("--workspace", default="/tmp/fl-sim", help="Workspace of the simulator")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--sites", type=int, default=2, help="Number of sites, each in every round (default: 2)")
    args = parser.parse_args()
    if args.sites < 1:
        parser.error("--sites must be at least 1")
    # The recipe sets both `min_clients` of the job and `num_clients` of FedAvg to this
    recipe = NumpyFedAvgRecipe(
        name=job_name(args.sites),
        min_clients=args.sites,
        num_rounds=args.rounds,
        model=[0.0, 0.0, 0.0],
        train_script="client.py",
    )
    if args.export_to:
        recipe.export(args.export_to)
        return
    run = recipe.execute(SimEnv(num_clients=args.sites, workspace_root=args.workspace))
    print("Result:", run.get_result(), "Status:", run.get_status())


if __name__ == "__main__":
    main()
