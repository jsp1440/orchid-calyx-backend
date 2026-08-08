# Calyx Program Autonomy — disabled-gate setup-python cache fix

The scheduled `Calyx Program Autonomy` workflow was failing during `actions/setup-python` post-job cache cleanup when the autonomy gate was disabled. In that fail-closed path no dependencies are installed, so the pip cache directory may not exist and cache finalization can fail even though no autonomous work was attempted.

The workflow now omits `cache: pip`. Dependency installation remains conditional on the existing autonomy gate, and all production database, owner, and enablement checks are unchanged.

This is an operational reliability correction only. It does not enable Calyx autonomy, relax any gate, authorize production mutation, grant merge/deploy/publication authority, or change autonomous executor capabilities.
