# References

## GA4GH

- [Workflow Execution Service (WES)](https://github.com/ga4gh/workflow-execution-service-schemas): the API in front. Version 1.1, in part.
- [Task Execution Service (TES)](https://github.com/ga4gh/task-execution-schemas): the API below. It lacks ports, secrets and time limits.
- [Data Repository Service (DRS)](https://github.com/ga4gh/data-repository-service-schemas): how data should be named, in the ideal design.
- [Tool Registry Service (TRS)](https://github.com/ga4gh/tool-registry-service-schemas): where job definitions should come from.
- [Service Registry](https://github.com/ga4gh-discovery/ga4gh-service-registry): how to find out what's there.
- [GA4GH Federated Analysis Work Stream](https://www.ga4gh.org/work_stream/federated-analysis-work-stream-formerly-cloud-work-stream/), formerly the Cloud Work Stream: owns WES, TES, TRS and DRS, and is the likely place for proposals.

## NVFlare

- [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare): the FL framework ([docs](https://nvflare.readthedocs.io/en/main/)).
- [Paper](https://arxiv.org/abs/2210.13291): NVIDIA FLARE: Federated Learning from Simulation to Real-World.
- [Certificate models](https://github.com/NVIDIA/NVFlare/blob/main/docs/user_guide/admin_guide/deployment/certificate_models.rst): provisioning, and how to separate keys per job.
- [Slurm job launcher](https://github.com/NVIDIA/NVFlare/blob/main/docs/user_guide/admin_guide/deployment/slurm_job_launcher.rst) and [Kubernetes launcher](https://github.com/NVIDIA/NVFlare/blob/main/docs/user_guide/admin_guide/deployment/kubernetes_task_launcher.rst): the template for [C3](../testbed/options.md#c3-a-tes-job-launcher-in-nvflare).
- [Security](https://github.com/NVIDIA/NVFlare/tree/main/docs/user_guide/admin_guide/security): site policies, among others.
- [Multi-study guide](https://github.com/NVIDIA/NVFlare/blob/main/docs/user_guide/admin_guide/multi_study_guide.rst): separating users on one federation.

## Implementations

- [Conquest](https://github.com/anuragxxd/conquest): the WES of [option A](../testbed/options.md#a-nvflare-inside-conquest).
- [proTES](https://github.com/elixir-cloud-aai/proTES): the TES gateway, used in [T4](../tests/t4-protes.md).
- [Funnel](https://github.com/calypr/funnel): the TES used here.
- [TESK](https://github.com/elixir-cloud-aai/TESK): a TES on Kubernetes, which real nodes may run.
- [FOCA](https://github.com/elixir-cloud-aai/foca): the framework for services of the organization.
- [Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry): a Service Registry for the nodes.

## Context

- [ELIXIR On-Cloud](https://elixir-on.cloud/): the network this is for.
- [Token exchange testbed](https://github.com/elixir-cloud-aai/token-exchange-flow-testbed): the structure of this repository, and the authentication this one leaves out.
- [Conquest: submit tasks to proTES](https://github.com/elixir-cloud-aai/generic-issues/issues/28): what option A is waiting for.
