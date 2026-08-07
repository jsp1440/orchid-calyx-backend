# AZURE-001 Release-Gate Checklist

Use this checklist before any bounded Azure taxonomy pilot.

- [ ] Exact candidate file identified and checksum recorded.
- [ ] Approved prior taxonomy snapshot supplied as baseline.
- [ ] Review reference assigned.
- [ ] Validator policy reviewed.
- [ ] Governance policy reviewed.
- [ ] Release-gate policy reviewed.
- [ ] `plan` command completed without creating an output bundle.
- [ ] Candidate and baseline are regular files, not symbolic links.
- [ ] Estimated evidence bundle is below 25 MB.
- [ ] Governed `run` completed with an exclusive output lock.
- [ ] `verify` confirms report, manifest, receipt, and completion-marker consistency.
- [ ] Receipt shows publication, database mutation, and Azure creation all unauthorized.
- [ ] Container image, if proposed, is pinned by SHA-256 digest.
- [ ] Generated Azure specification has `provision=false`, no public ingress, and no database access.
- [ ] Azure credit linkage and budget alerts confirmed separately.
- [ ] Explicit go/no-go approval obtained before any Azure provisioning.
