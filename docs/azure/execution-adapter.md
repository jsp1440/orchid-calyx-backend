# Governed Azure Container Apps Jobs execution

Status: optional implementation, **disabled by default; no deployment or spending authorization**.

## Canonical contracts

`app/calyx_orchestrator/executor.py::ExecutorAdapter` remains the execution
interface. `GovernedAssignment` and `ExecutionReceipt` are unchanged.
`PersistentProgramWorker.claim` remains admission and lease authority;
`LeaseExecutionBridge` remains settlement authority; the existing program
repository releases dependent work. Azure never selects missions, creates
programs, owns dependencies, refills a queue, or authorizes publication.

Brain mission contracts are `BuildAdmissionRequest`, `GovernedBuildQueue`, and
`canonical_brain.scheduler_bridge`. Governing repository Brain records include
`architecture:brain`, `decision:brain-canonical-memory`, and
`intent:enable-governed-autonomy` in `canonical_brain/fixtures.py`. These are
local governed-contract fixtures, not a claim that the live Brain was queried.
The Azure landing-zone and cost guardrails remain applicable.

This is NEW provider work, related to #457 and parent #384. PR #1795 is not
modified, replaced, or superseded. Its evolving handoff is not assumed to be on
`main`. This adapter is separate from the deterministic autonomous cycle:
that cycle's registry still refuses external-side-effect executors. Render,
GitHub, and existing deterministic paths are unchanged.

## Explicit provider selection

Only a trusted control-plane caller may choose `AzureContainerAppsExecutor`
for an already-claimed `azure_bounded_job` role. Merely setting environment
variables does not change a scheduler, registry, route, or existing worker.
No HTTP endpoint accepting execution grants is added.

```python
config = AzureJobConfig.from_environ(operator_environment)
credential = managed_identity_credential(config)
reader = ManagedBlobReceiptReader(
    credential, account=approved_receipt_account, container=approved_receipt_container,
)
client = AzureContainerAppsJobClient(ManagedAzureHttp(credential), reader)
assignment = governed_assignment_from_claimed_job(db, owner=owner, job=claimed_job)
executor = AzureContainerAppsExecutor(
    db, config=config, client=client, owner=owner,
    worker_id=claimed_job.lease_owner, lease_token=claimed_job.lease_token,
    grant_resolver=trusted_approved_budget_reservation_lookup,
)
receipt = executor.execute(assignment)
completed = executor.settle(assignment, receipt)
```

The injected grant lookup must return an **existing independently approved**
`AzureExecutionGrant`, or `None`. It must not invent approvals or treat mission
prose, persisted job inputs, or an enabled flag as authorization. The grant binds
the task, canonical input checksum, lease digest, exact provider configuration
checksum, Azure resource, expiry, approval reference, and reserved micro-USD
budget. The configured maximum must fit that reserved budget.
The adapter neither reserves funds in an external ledger nor measures actual
Azure spend: a real approved reservation and conservative cost estimate are
operator prerequisites. The fake demo's synthetic grant conveys no authority
outside the demo.

## Configuration

Use an explicit environment mapping. `CALYX_AZURE_ENABLED` defaults to `false`.
Do not store credentials or resource-specific privileged values in repository
configuration. Install `requirements-azure.txt` only for approved managed-auth
execution; provider-free validation needs no Azure SDK.

| Environment variable | Contract |
|---|---|
| `CALYX_AZURE_ENABLED` | `true`/`1` only after the separate owner deployment/spending checkpoint |
| `CALYX_AZURE_SUBSCRIPTION_ID` | Approved subscription |
| `CALYX_AZURE_RESOURCE_GROUP` | Non-production resource group |
| `CALYX_AZURE_ENVIRONMENT_NAME` | Existing Container Apps managed environment in that group |
| `CALYX_AZURE_JOB_NAME` | One existing manual Container Apps Job |
| `CALYX_AZURE_JOB_IDENTITY_RESOURCE_ID` | Exact user-assigned workload identity resource ID in that group |
| `CALYX_AZURE_MANAGED_IDENTITY_CLIENT_ID` | Dispatcher's user-assigned managed identity client ID |
| `CALYX_AZURE_CONTAINER_NAME` | One approved container |
| `CALYX_AZURE_IMAGE` | Immutable `repository@sha256:<64 lowercase hex>` |
| `CALYX_AZURE_MAX_RUNTIME_SECONDS` | 1-3600, default 60 |
| `CALYX_AZURE_API_TIMEOUT_SECONDS` | 1-30, default 10 |
| `CALYX_AZURE_POLL_SECONDS` | 1-60, default 2 |
| `CALYX_AZURE_MAX_POLLS` | 1-3600, default 30 |
| `CALYX_AZURE_MAX_COST_MICROUSD` | Positive approved upper-bound estimate; default 0 fails closed |

Managed authentication uses `ManagedIdentityCredential`, never CLI credential
fallback, client secrets, or subscription-owner credentials. The dispatcher
requires narrowly scoped job get/start/execution-get/stop and private receipt
read permissions. The workload identity is separate; it must not have
production DB/KG, publication, deployment, paid AI, or scheduler authority.

## Job and result contract

Before start, the adapter checks resource/environment/identity, manual trigger,
one replica and completion, zero Azure retries, a bounded replica timeout, and
one pinned container at 0.5 CPU / 1 GiB. Init containers, volumes, container
command/argument overrides, and unapproved environment values are refused.
The deployable worker's five exact identity/receipt-storage environment values
are explicitly allowlisted and preserved when the ARM start template is built;
see [worker deployment](worker-deployment.md) for the image/build/checklist.
No resource creation, schedule update, or configuration mutation is implemented.

Start sends `CALYX_EXECUTION_PAYLOAD` to the approved image's entrypoint.
Payloads exceeding 16 KiB are rejected; large/private work must use bounded
approved artifact references rather than inline content. The payload includes
durable assignment/program/job identity, checksum, lease digest and expiry,
runtime limit, canonical inputs, capabilities, provenance, and approval
reference. **It does not include the lease token.** Canonical assignment
governance fields are not rewritten to pretend that deployment/publication
authority was granted. Only the separate scoped execution grant authorizes
this provider dispatch.

The operator-approved image must enforce the lease expiry, checksum, allowed
operation/capabilities, bounded runtime, and no production/scientific side
effects. It writes an immutable JSON `ExecutionReceipt` to private Blob:

`<account>/<container>/<assignment_id>/<lease_digest>/receipt.json`

The worker's artifact destination is an approved image/workload configuration,
not mission-supplied storage credentials. Use conditional create/immutability
and least-privilege workload write access. The dispatcher has read-only access.
The JSON has the existing receipt fields, `executor_key=azure_container_apps_job_v1`,
matching assignment/program/job/input identities, `state=delivered`,
`outcome=DELIVERED`, a verified canonical output checksum, evidence URIs, and
output containing the exact `lease_digest` and ARM `execution_reference`.

Azure `Succeeded` without this artifact is **not** success. Missing, malformed,
wrong-task, wrong-lease, or checksum-mismatched receipts block settlement.
Provider evidence retains ARM execution/operation references and artifact/log
URIs supplied by the verified receipt. Raw console-log download is not
implemented; operators correlate the ARM execution name in the approved
private Azure Monitor workspace. Unavailable logs must not be represented as
captured evidence. Fake references use `fake-azure:` and never imply live logs.

ARM API version is `2024-03-01`. The implementation follows Microsoft's
[Start](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs/start?view=rest-resource-manager-containerapps-2024-03-01)
and [Stop Execution](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs/stop-execution?view=rest-resource-manager-containerapps-2024-03-01)
contracts. Job-scoped execution/operation references are allowlisted.
An unfamiliar `202 Location` shape is refused and requires reconciliation,
not a permissive redirect or another start call. Validate the target region's
actual Location shape during the owner-authorized canary before broad use.

## Durability, fencing, recovery, and retry

Apply `migrations/181_calyx_azure_execution_records.sql` to an approved
non-production Calyx database before selecting the provider. This idempotent
additive table is a write-ahead **evidence journal**, not a new task queue.
No startup migration runs automatically.

The task primary key permits at most one start attempt per durable job,
including across session/process restart. A committed `starting` disposition
precedes ARM start. Network failure or process loss can make acceptance
unknown; that uncertainty is retained and the adapter never blindly restarts.
Duplicate dispatch raises `AZURE_DUPLICATE_DISPATCH` before a second start.

`resume(assignment)` returns a recorded receipt or polls a known execution
under the **same still-live lease and original persisted deadline**. It does
not extend a lease, runtime, or budget. If start has no known reference, resume
records `AZURE_START_OUTCOME_UNKNOWN`. An expired/replaced lease is fenced,
even if Azure later reports success; it cannot settle canonical work.

Timeout/poll exhaustion requests bounded stop and records whether reconciliation
is still required. A stop request is not proof that a remote job stopped.
API failure, provider failure, malformed results, interruption, and blocked
budget/authorization have durable evidence. Failures settle through the normal
bridge as BLOCKED with the existing human-action/retry guidance; no dependent
work is released on those outcomes.

Retries use a **new governed program/job revision** with `retry_of`, a repair
reason, fresh canonical admission/lease, and a new approved reservation. First
reconcile any unknown or still-running prior Azure execution. Do not clear the
journal, replay the old task, or use lease recovery to bypass this boundary.
Existing Calyx attempt ceilings and owner gates still apply. This adapter does
not automatically manufacture or schedule retry revisions.

## Provider-free demonstration and validation

From the repository root (Windows uses `py`):

```text
py -m scripts.oc_azure_execution_demo
py -m pytest -q tests\test_calyx_azure_execution.py
```

The demo uses an explicitly constructed local SQLite database, repository Brain
fixtures/admission/scheduler projection, normal durable Calyx claim, fake Azure
execution, verified receipt, canonical settlement, and downstream queued
eligibility. It never reads an ambient production database URL or calls Azure,
an AI provider, or a billing service. It does not certify live Brain/Azure,
scientific acceptance, or independent checker PASS.

## Operator deployment checklist (not authorization)

- [ ] Keep Azure disabled and retain existing execution paths until review.
- [ ] Independently review the exact PR head and required checks.
- [ ] Obtain owner approval for non-production resource creation, dispatch,
      migration, permissions, and the bounded spending reservation.
- [ ] Verify nonprofit credit/billing linkage, regional pricing, the #457 pilot
      ceiling, logs/storage/egress costs, alerts, and conservative job cost caps.
- [ ] Prepare the manual job/environment and pinned bounded worker image in a
      separate authorized deployment; disable Azure-native retry/scheduling.
- [ ] Verify least-privilege dispatcher/workload identities and private
      immutable receipt storage. No production access or paid-model credentials.
- [ ] Apply the additive journal migration to non-production only.
- [ ] Wire an approved reservation lookup and private receipt reader into the
      trusted post-admission caller. Never accept grants from request prose.
- [ ] Run a separately approved non-production canary covering actual ARM
      Location/status, worker receipt, timeout/stop, restart, duplicate, and
      stale-lease behavior; verify private log correlation and measured spend.
- [ ] Confirm failed and successful canonical settlement and dependency
      eligibility. Scientific publication and main integration remain gated.
- [ ] Roll back selection by disabling Azure and removing the explicit caller
      binding. Reconcile already-started executions; retain journal/receipts.
      Do not delete evidence or drop the table as a routine rollback.

Remaining live prerequisites are the approved worker image/resources/identities,
budget reservation integration, non-production migration, live receipt/log
canary, and independent exact-head acceptance. None are represented as
completed by the local proof.
