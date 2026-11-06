# About

## Contact

[Open an issue](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues) in this repository for anything about the testbed. For the services around it, see [ELIXIR On-Cloud](https://elixir-on.cloud/).

## Contributors

See the repository's [contributors](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/graphs/contributors). Written with AI assistance, as the commits say.

## Citation

There's no citable release. To refer to the testbed, give the repository's URL and the commit you used.

## License

[Apache-2.0](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/LICENSE). The test set is made up here and has the same licence ([details](../testbed/components.md#test-set)). The job follows NVFlare's `hello-numpy` example, and `tests/fake_idp.py` is cut down from proTES, both Apache-2.0.

## Acknowledgements

The authors of [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) and [Funnel](https://github.com/calypr/funnel), which this depends on.

## Contributing and development

Light by design: it's a sandbox. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/), with a subject of at most 50 characters. Add every shortcut to [Shortcuts and hacks](../testbed/shortcuts.md), and every test to [Tests](../tests/index.md). CI lints, builds the docs and runs the local tests; the only required check is `CI passed`.

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
