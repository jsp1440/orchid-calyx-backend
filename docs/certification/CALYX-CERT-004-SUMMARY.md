# CALYX-CERT-004 summary

This change prevents false-positive repair certification. The server verifies that a repair produced a commit and advanced the target pull request head before reporting a committed repair. The certification CLI now derives an explicit outcome and never sets `repair_applied` solely because the endpoint returned successfully.
