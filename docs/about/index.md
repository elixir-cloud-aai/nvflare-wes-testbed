# About

## Contact

[Open an issue](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues) in this repository for anything about the testbed. For the services around it, see [ELIXIR On-Cloud](https://elixir-on.cloud/).

## Contributors

See the repository's [contributors](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/graphs/contributors). Written with AI assistance, as the commits say.

## Citation

Cite a release, with the metadata in [`CITATION.cff`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/CITATION.cff); a DOI follows with the first release. The notes of each release are in [Releases](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/releases) and under `docs/releases/`.

## License

[Apache-2.0](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/LICENSE). The test set is made up here and has the same licence ([details](../testbed/components.md#test-set)). The job follows NVFlare's `hello-numpy` example, and `tests/fake_idp.py` is cut down from proTES, both Apache-2.0.

## Acknowledgements

The authors of [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) and [Funnel](https://github.com/calypr/funnel), which this depends on.

## Contributing and development

Light by design: it's a sandbox. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/), with a subject of at most 50 characters. Add every shortcut to [Shortcuts and hacks](../testbed/shortcuts.md), and every test to [Tests](../tests/index.md). CI lints, builds the docs, runs the local tests and checks the chart for Rahti (`tests/chart.sh`, which needs Helm and yq); the only required check is `CI passed`.

The linters run through [pre-commit](https://pre-commit.com/) (`.pre-commit-config.yaml`): ruff, gitleaks, actionlint and some file checks. To run them on each commit, then once on all files, and gitleaks over the whole checkout, as CI does (the second command only scans staged changes with it):

```sh
python3 -m venv .venv && .venv/bin/pip install '.[lint]' && .venv/bin/pre-commit install
.venv/bin/pre-commit run --all-files
.venv/bin/pre-commit run --all-files --hook-stage manual gitleaks-all
```

To build the docs:

```sh
python3 -m venv .venv && .venv/bin/pip install '.[docs]' && .venv/bin/mkdocs serve
```

To change the job or the data, see [`testset/README.md`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/testset/README.md).

## Releasing

Releases are version tags `vX.Y.Z` on a commit of `dev`, from which `.github/workflows/release.yml` publishes the image of the participants as `elixircloud/nvflare-wes-testbed:X.Y.Z`, scanned, signed and with its build provenance attested, and creates the GitHub release, a pre-release until 1.0.0. The chart of the hub isn't released: install it from the repository at the tag.

1. **Release preparation:** a pull request sets the version in `pyproject.toml` and `CITATION.cff`, and `date-released` in `CITATION.cff` to the day of the tag, and adds the curated notes `docs/releases/X.Y.Z.md`, in the organization's format: an intro paragraph, then the sections `## Breaking changes`, `## Features`, `## Security`, `## Fixes`, `## Documentation` and `## Maintenance` (empty ones left out), each bullet ending with its issue and pull request numbers. Add the notes to the nav under "Releases", newest first.
2. **Tag** the merged commit, once CI passed for its push to `dev`, with a signed annotated tag, and push only that tag.
3. **Approve** the jobs `Push release image` and `Release image` in the `release` environment, and `Notify Pubgrade` if Pubgrade is configured (see below).

The workflow's first job, `Prepare release`, fails before anything is published unless the tag is `vX.Y.Z`, annotated, with a signature that GitHub verified, on a commit of `dev` for which CI passed, with the same version in `pyproject.toml` and `CITATION.cff`, a `date-released`, and notes in the format, and if a published release of the tag exists already. The image is pushed by digest and scanned first, and only signed and tagged once the scan found no fixable critical or high vulnerabilities. Accepted findings are listed in `.trivyignore.yaml`, each with its reason and an expiry date; the scan needs that file, even with no entries. Tags and releases are never changed or reused: a release with a mistake is fixed by the next one. If a run fails, re-run only its failed jobs, which reuse the pushed digest; a re-run of all jobs stops once the image's version tag exists. You approve twice: `Push release image` and `Release image` both run in the environment `release`, and a third time for `Notify Pubgrade` if Pubgrade is configured. A fork can try the workflow on a test tag, with its repository variable `DOCKERHUB_ORG` set to its own Docker Hub organization, and an environment `release` with its own Docker Hub secrets.

The repository needs an environment `release`, with the maintainer as required reviewer, a deployment policy that allows only tags `v*`, and the Docker Hub secrets `DOCKERHUB_LOGIN` and `DOCKERHUB_TOKEN`, tag rulesets that allow only release tags, created by the maintainer.

After the image is tagged (without waiting for the GitHub release), the workflow registers it, with the release tag, at [Pubgrade](https://github.com/elixir-cloud-aai/Pubgrade) (`POST /repositories/{id}/builds`, through Pubgrade's action [`actions/notify`](https://github.com/elixir-cloud-aai/Pubgrade/tree/344a58adc1c871135f86c404eb33ed91011886ad/actions/notify)), which notifies the deployments subscribed to the release tag (or to every tag, with `*`); Pubgrade doesn't tell pre-releases apart, so a `*` subscription gets every release. The action masks the token and retries a request only if it never reached Pubgrade, so that one run registers the build at most once; re-running the job registers it again. This needs Pubgrade's publish mode ([#33](https://github.com/elixir-cloud-aai/Pubgrade/issues/33)) and these settings:

| Setting | Kind | Where | Meaning |
| --- | --- | --- | --- |
| `PUBGRADE_URL` | Variable | Repository | Base URL of the Pubgrade API, with `https://`. Switches the notification on. |
| `PUBGRADE_REPOSITORY_ID` | Variable | Repository | The identifier from registering the repository in Pubgrade |
| `PUBGRADE_TOKEN` | Secret | The `release` environment | The access token from registering the repository in Pubgrade |

Without `PUBGRADE_URL`, the job `Notify Pubgrade` is skipped, so releases (and fork dry runs) don't wait for its approval.

Set `PUBGRADE_URL` for the repository, not in the `release` environment: a job's condition is evaluated before the job enters its environment, so a variable there doesn't switch the job on (and would override the repository's URL within the job). An organization variable would switch it on for every repository it is shared with, also those without a Pubgrade token.

With `PUBGRADE_URL`, the job waits for an approval in the `release` environment, like pushing and releasing the image, and fails if one of the other settings is missing or invalid: the identifier and the token may only hold letters, digits, `.`, `~` and `-` (as Pubgrade issues them).

If only this job fails or is rejected, the image is released all the same: fix the settings and re-run the job, or leave it; don't release a new version for it. Unless it failed on an invalid setting or with "Could not reach Pubgrade (curl exit status 6)" or "(… 7)" (no connection), Pubgrade may have registered the build all the same: check the repository's builds (`GET /repositories/{id}/builds`) before re-running it, as re-running notifies the subscribed deployments again.
