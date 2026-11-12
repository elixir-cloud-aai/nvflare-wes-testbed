#!/usr/bin/env bash
# Kill the client of site 2 in the middle of a run: test T6 of the docs.
# Needs a running testbed (`docker compose up -d --wait fl-hub`) and only Docker.
set -euo pipefail

wes() {
    docker compose exec -T fl-hub python3 -c "
import sys, requests
base = 'http://localhost:8080/ga4gh/wes/v1'
if sys.argv[1] == 'submit':
    print(requests.post(f'{base}/runs', data={
        'workflow_type': 'NVFLARE', 'workflow_type_version': '2.9',
        'workflow_url': 'logreg-fedavg'}).json()['run_id'])
else:
    print(requests.get(f'{base}/runs/{sys.argv[2]}').text)
" "$@"
}

run_id="$(wes submit)"
echo "run ${run_id}"
victim=""
for _ in $(seq 1 60); do
    victim="$(docker ps -q --filter label=nvflare-wes-testbed=task --filter network=nvflare-wes-testbed-site-2)"
    [ -n "${victim}" ] && break
    sleep 1
done
[ -n "${victim}" ] || { echo "No task of site 2 found"; exit 1; }
sleep 12
echo "Killing the task of site 2"
docker rm -f "${victim}" >/dev/null
started="${SECONDS}"
for _ in $(seq 1 120); do
    log="$(wes log "${run_id}")"
    state="$(printf '%s' "${log}" | sed -E 's/.*"run_id":"[^"]*","state":"([A-Z_]+)".*/\1/')"
    case "${state}" in
        COMPLETE | EXECUTOR_ERROR | SYSTEM_ERROR | CANCELED) break ;;
    esac
    sleep 2
done
echo "Run ended with ${state}, $((SECONDS - started)) s after the kill"
echo "${log}"
# Funnel marks a task as canceled first, and stops its container a little later
left=1
for _ in $(seq 1 30); do
    left="$(docker ps -q --filter label=nvflare-wes-testbed=task | wc -l | tr -d ' ')"
    [ "${left}" = "0" ] && break
    sleep 1
done
echo "Task containers left: ${left}, $((SECONDS - started)) s after the kill"
if [ "${state}" = "COMPLETE" ]; then
    echo "[FAIL] the run must not count as complete"
    exit 1
fi
if [ "${left}" != "0" ]; then
    echo "[FAIL] task containers are left behind"
    exit 1
fi
echo "[ok] the run failed, and left no task behind"
