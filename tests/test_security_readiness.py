import unittest

from app.security_readiness import CLOSURE_EVIDENCE, Exposure, Severity, closure_gate


class SecurityReadinessTests(unittest.TestCase):
    def test_known_public_exploit_is_sev1(self):
        result = Exposure(
            affected_assets=1,
            internet_exposure=5,
            privilege=3,
            connectivity=3,
            data_sensitivity=3,
            known_exploit=True,
        )
        self.assertEqual(result.severity, Severity.SEV1)

    def test_runtime_and_compensating_controls_reduce_score(self):
        exposed = Exposure(2, 4, 3, 3, 3)
        controlled = Exposure(2, 4, 3, 3, 3, runtime_reachable=False, compensating_control=True)
        self.assertLess(controlled.blast_radius, exposed.blast_radius)

    def test_closure_fails_closed_without_all_evidence(self):
        result = closure_gate(["patched_artifacts_rebuilt"])
        self.assertFalse(result["close_allowed"])
        self.assertIn("production_reverified", result["missing_evidence"])

    def test_closure_requires_and_accepts_complete_evidence(self):
        result = closure_gate(CLOSURE_EVIDENCE)
        self.assertEqual(result["status"], "verified_closed")
        self.assertTrue(result["close_allowed"])


if __name__ == "__main__":
    unittest.main()
