# oc-brain-worker: copyable non-production container handoff

Status: **code/build preparation only**. No image publishing, Azure deployment,
resource provisioning, role assignment, paid model, or production dispatch is
authorized by these commands. Default provider and worker flags remain false.
This extends draft #1797, classification CONTINUE; #1795 is untouched.

## What is deployable

`containers/azure-worker/Dockerfile` builds a Linux amd64, non-root UID/GID
65532 image with an exec-form PID-1 entrypoint. The runtime copies only the
bounded worker and existing `GovernedAssignment`/`ExecutionReceipt` contracts,
not the application, database clients, scheduler, Brain service, or AI SDKs.
It performs the adapter's bounded **input/checksum/identity/provenance
verification** operation. It does not implement arbitrary scientific research
or open-ended code execution. Unknown operations/capabilities fail closed.

One job gets one canonical already-admitted payload. The worker checks input
checksum, task/program identity, non-mutating governance, provenance,
lease-digest format, absolute expiry, and a maximum 60-second runtime. The
worker cannot independently query lease replacement without the Calyx DB and
does not claim otherwise: live supersession/holder fencing remains enforced
by canonical Calyx dispatch and settlement. No DB credentials enter the image.

Valid live results are conditionally created (`If-None-Match: *`) at:

`https://<account>.blob.core.windows.net/<container>/<assignment_id>/<lease_digest>/receipt.json`

Existing artifacts are never overwritten or silently treated as success.
Upload failure, interruption, expired/invalid work, or a verification failure
exits nonzero and emits a sanitized error. For a still-valid bound envelope,
failure receipt persistence is attempted explicitly; unavailable failure
evidence is reported rather than hidden. Calyx retains the provider journal
and handles the failed execution. Immutable Blob receipts carry the existing
execution schema, output checksum, provenance, and exact execution/lease
identity. No payloads, access tokens, or raw exception strings are logged.

## Image/build identity

Repository: `ghcr.io/jsp1440/orchid-calyx-backend/oc-brain-worker`.
Exact commit tag is always:

```text
ghcr.io/jsp1440/orchid-calyx-backend/oc-brain-worker:sha-<40-hex-verified-head>
```

Generate the exact copyable tag from the checkout:

```powershell
$HeadSha = (git rev-parse HEAD).Trim()
$Image = "ghcr.io/jsp1440/orchid-calyx-backend/oc-brain-worker:sha-$HeadSha"
$Image
```

The PR evidence names the exact tested head/tag. **No published image or GHCR
manifest digest exists until owner-authorized publishing occurs.** A local
Docker image ID is not a GHCR manifest digest. After approved publishing use:

```text
ghcr.io/jsp1440/orchid-calyx-backend/oc-brain-worker@sha256:<published-manifest-digest>
```

The adapter/template require this digest, not `latest` or a mutable tag.
The base is `python:3.12.15-alpine3.24` pinned to
`sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`.
Python wheels/transitive dependencies are version/hash-locked in
`containers/azure-worker/requirements.lock`. The Linux lock was generated with
uv 0.9.2; updates require regenerating, reviewing, rebuilding, and scanning.

```powershell
py -m uv pip compile containers\azure-worker\requirements.in `
  --python-version 3.12 --python-platform x86_64-unknown-linux-musl `
  --generate-hashes --output-file containers\azure-worker\requirements.lock
```

## Local actual-container validation

Requires an already-running Docker engine; installing/enabling Docker/WSL or
changing host privileges is not part of this assignment. Do not substitute a
native Python run for actual-container evidence.

```powershell
$HeadSha = (git rev-parse HEAD).Trim()
$Image = "ghcr.io/jsp1440/orchid-calyx-backend/oc-brain-worker:sha-$HeadSha"
$Epoch = (git show -s --format=%ct HEAD).Trim()
docker buildx build --platform linux/amd64 --load --provenance=false `
  --build-arg "SOURCE_REVISION=$HeadSha" --build-arg "SOURCE_DATE_EPOCH=$Epoch" `
  --file containers\azure-worker\Dockerfile --tag $Image .
py -m scripts.oc_azure_container_proof --image $Image
```

The fake Azure transport starts the **actual image** with no network,
read-only rootfs, dropped capabilities, no-new-privileges, PID/memory/CPU
bounds, non-root identity, and `--pull=never`. It submits a Brain-admitted
durable Calyx task, verifies the container-produced receipt, refuses duplicate
dispatch and stale-holder settlement, and verifies canonical settlement plus
next Brain-work eligibility. Existing adapter tests additionally exercise
lease expiry, supersession, process recovery, budgets, and API/timeout failure.
The native subprocess unit proof is labelled separately from the Docker proof.

## Build workflow and publishing gate

`.github/workflows/calyx-azure-container.yml` builds without push on PRs,
binding the **PR head SHA**, not the synthetic merge commit. Actions are
commit-pinned. It runs focused worker/adapter tests, actual-image fake-Azure
proof, non-root checks, HIGH/CRITICAL vulnerability and secret scanning with
Trivy 0.75.0, and emits a CycloneDX SBOM plus small build/evidence artifacts.
No Azure login, production secrets, or package-write permission in build job.
The base, wheel hashes, source SHA, and SOURCE_DATE_EPOCH fix the build inputs;
bit-for-bit reproducibility is not claimed without comparing two actual builds.
Vulnerability DB freshness remains an external validation input.

Default `workflow_dispatch publish=false`. Prepared GHCR publish requires all:

- owner authorizes publishing/visibility and verifies GitHub Actions/package
  storage/bandwidth allowance (this code does not certify billing);
- repository variable `CALYX_AZURE_GHCR_PUBLISH_AUTHORIZED=true`;
- manual workflow input `publish=true`;
- successful build, worker proof and security scan;
- protected environment `azure-worker-ghcr-publish` with required reviewers and
  prevent-self-review enabled (API verification fails closed);
- a new SHA tag (existing tags are refused, and unknown registry errors block).

Only that separately gated job gets `packages: write`, loads the exact verified
build artifact, and pushes one SHA tag. No automatic public visibility change,
`latest` tag, Azure deployment, or dispatch. Owner must choose visibility.
For a private GHCR package, Azure managed identity **cannot authenticate to
GHCR**: an owner-approved pull-only registry credential is required, or the
owner must separately approve public package visibility. No such credential
or public-code disclosure is created by this implementation.

## Deployment target and startup

| Setting | Exact configured value |
|---|---|
| Subscription display name | `Azure subscription 1` |
| Subscription GUID | **Missing operator input**; display name is not a resource ID |
| Resource group | `RG-ORCHID-CONTINUUM-AGENTS` |
| Region | `westus2` (West US 2) |
| Job | `oc-brain-worker` |
| Environment | Existing approved Consumption environment; **name required** |
| Workload profile | `Consumption` |
| Container | `worker` |
| Trigger | `Manual` |
| CPU / memory | `0.5` / `1Gi` |
| Parallelism / completion count | `1` / `1` |
| Replica retry / timeout | `0` / `60` seconds |
| Startup | `python -m app.calyx_orchestrator.azure_worker` |

Leave Azure command/args **empty**: Docker's exec-form ENTRYPOINT supplies the
startup. The adapter refuses arbitrary overrides. The ARM template is
`containers/azure-worker/job.template.json`; it creates only the manual job
against pre-existing environment/identity/storage. It never starts a job.
`workerEnabled` defaults to false. Subscription GUID, environment, workload
identity, private receipt storage, and published digest cannot be fabricated.

## Required environment and managed identity

Trusted job template env (not mission-supplied):

| Variable | Value |
|---|---|
| `CALYX_AZURE_WORKER_ENABLED` | `false` initially; `true` only at approved canary gate |
| `CALYX_WORKER_JOB_RESOURCE_ID` | `/subscriptions/<GUID>/resourceGroups/RG-ORCHID-CONTINUUM-AGENTS/providers/Microsoft.App/jobs/oc-brain-worker` |
| `CALYX_WORKER_IDENTITY_CLIENT_ID` | Approved **workload** user-assigned identity client GUID |
| `CALYX_RECEIPT_STORAGE_ACCOUNT` | Approved private non-production receipt account |
| `CALYX_RECEIPT_CONTAINER` | Approved receipt container |

Per-execution env: `CALYX_EXECUTION_PAYLOAD`, generated exclusively by the
canonical admitted Calyx adapter, includes checksum/task/program/provenance,
lease digest/expiry and approved reservation reference, **never lease token**.
The platform supplies `CONTAINER_APP_JOB_EXECUTION_NAME`; the worker refuses
missing/invalid names rather than inventing an execution identity. Confirm
this platform value during the approved regional canary. No probe job was
dispatched to verify it in this assignment.

Dispatcher env also requires the configuration in `execution-adapter.md`,
including `CALYX_AZURE_SUBSCRIPTION_ID=<GUID>`,
`CALYX_AZURE_RESOURCE_GROUP=RG-ORCHID-CONTINUUM-AGENTS`,
`CALYX_AZURE_JOB_NAME=oc-brain-worker`, environment/identity/digest and positive
approved budget cap. Added exact fields:
`CALYX_AZURE_RECEIPT_STORAGE_ACCOUNT`, `CALYX_AZURE_RECEIPT_CONTAINER`,
`CALYX_AZURE_WORKER_IDENTITY_CLIENT_ID`. The adapter verifies and preserves
**only these exact approved worker env values** in the execution template.
`CALYX_AZURE_ENABLED` remains false until the owner authorizes the test.

Permissions (separate identities, no credentials in source):

- Workload identity: create/write receipt blobs **only in the private receipt
  container**, with overwrite blocked by conditional create and storage
  immutability policy. A container-scoped custom data role using
  `Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write`
  is preferred; avoid broad account-contributor permissions. Identity endpoint
  available only to the approved container. No Calyx DB, secrets, production,
  AI, deployment, publication, or job-start permissions.
- Dispatcher identity: job-scoped custom ARM actions
  `Microsoft.App/jobs/read`, `Microsoft.App/jobs/start/action`,
  `Microsoft.App/jobs/executions/read`, `Microsoft.App/jobs/execution/read`,
  `Microsoft.App/jobs/stop/execution/action`; add specific job-scoped async
  operation reads only if the regional ARM response requires them.
  Private receipt container read via `Storage Blob Data Reader`. Optional
  approved logs read is separate. No `listSecrets`, wildcards, job-write,
  production DB or spending authority. Start permission can override an
  execution image/use its identity: trust only the governed dispatcher, not
  untrusted mission callers.
- Deployment identity: separately owner-authorized job deployment/identity
  attachment permissions; never used by this worker or CI build.

## Exact controlled-test checklist

These are copyable **future owner/operator commands**, not authorization and
were not executed against Azure here.

1. Review exact head, actual-image test/security reports, SBOM, billing cap,
   and independently authorize package visibility/publish plus one bounded
   non-production job. Approve private storage immutability/retention and
   least-privilege identities; verify Consumption environment in westus2.
2. Run the protected publish workflow for the reviewed SHA. Record GHCR
   manifest digest and exact-head evidence. Do not reuse an unverified tag.
3. Resolve the target subscription ID without copying any secret:

   ```powershell
   $SubscriptionId = (az account show --subscription "Azure subscription 1" --query id -o tsv).Trim()
   $ResourceGroup = "RG-ORCHID-CONTINUUM-AGENTS"
   ```

4. Populate existing approved resource names and **real published** digest:

   ```powershell
   $EnvironmentName = "<approved-existing-Consumption-environment>"
   $IdentityName = "<approved-existing-workload-identity>"
   $IdentityClientId = "<workload-managed-identity-client-GUID>"
   $ReceiptAccount = "<approved-private-nonproduction-storage>"
   $ReceiptContainer = "<approved-receipt-container>"
   $ImageDigest = "sha256:<real-published-manifest-digest>"
   ```

5. After owner deployment authorization, validate/preview/create the
   disabled worker using the template; no `az containerapp job start`:

   ```powershell
   az deployment group validate --subscription $SubscriptionId --resource-group $ResourceGroup `
     --template-file containers\azure-worker\job.template.json `
     --parameters environmentName=$EnvironmentName workloadIdentityName=$IdentityName `
       workloadIdentityClientId=$IdentityClientId imageDigest=$ImageDigest `
       receiptStorageAccount=$ReceiptAccount receiptContainer=$ReceiptContainer workerEnabled=false
   az deployment group what-if --subscription $SubscriptionId --resource-group $ResourceGroup `
     --template-file containers\azure-worker\job.template.json `
     --parameters environmentName=$EnvironmentName workloadIdentityName=$IdentityName `
       workloadIdentityClientId=$IdentityClientId imageDigest=$ImageDigest `
       receiptStorageAccount=$ReceiptAccount receiptContainer=$ReceiptContainer workerEnabled=false
   ```

   Creation uses the same arguments with `az deployment group create` **only
   after preview approval**. Private GHCR requires owner-supplied
   `registryUsername`/secure `registryPassword` through the deployment's secure
   input mechanism, not CLI plaintext, repository files, or logs. Never turn
   a private source image public just to bypass a pull error.
6. Approve the journal migration on non-production Calyx, establish a real
   approved per-task budget reservation, enable exact worker template and
   dispatcher selection only for this canary, and claim the legitimate
   `azure_bounded_job` input-verification task through Calyx. Call the existing
   adapter, **not** a direct ungoverned `az ... start`. Verify artifact,
   observed execution ID/expiry/lease fences, canonical settlement and next
   work eligibility; record observed runtime/cost and private logs.
7. Disable provider/worker after the one test; reconcile any unknown remote
   state and retain journal/receipts. No scientific or production authority.

**Single next action:** obtain the owner-approved canary release packet
(exact image build/security evidence, GHCR publishing/visibility authorization,
subscription/resource identities, private receipt store and bounded reservation).
This permits the operator to publish/configure **one non-production test**
through the checklist; without it, no Azure dispatch is executable or authorized.
