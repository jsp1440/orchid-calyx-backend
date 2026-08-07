from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from starlette.requests import Request

from app.mission_control_access import AuthenticatedIdentity, PrincipalResolver
from app.mission_control_access.qualification_registry import (
    QualificationRegistryError,
    reviewer_qualification_claims,
)
from app.review_api.dependencies import _identity_from_owner_session


class ReviewerQualificationRegistryTests(unittest.TestCase):
    def test_missing_registry_grants_nothing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            claims = reviewer_qualification_claims("owner", auth_source="owner_session")
        self.assertEqual(claims.qualifications, ())
        self.assertEqual(claims.specialties, ())

    def test_owner_session_can_receive_only_server_configured_scientific_qualification(self) -> None:
        registry = {
            "owner": {
                "qualifications": ["qualified.science-reviewer"],
                "specialties": ["orchid taxonomy"],
            }
        }
        with patch.dict(
            os.environ,
            {"MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON": json.dumps(registry)},
            clear=True,
        ):
            claims = reviewer_qualification_claims("owner", auth_source="owner_session")
        self.assertEqual(claims.qualifications, ("qualified.science-reviewer",))
        self.assertEqual(claims.specialties, ("orchid taxonomy",))

    def test_api_key_cannot_receive_scientific_qualification_from_registry(self) -> None:
        registry = {
            "backend_api_key": {
                "qualifications": ["qualified.publication-reviewer"],
            }
        }
        with patch.dict(
            os.environ,
            {"MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON": json.dumps(registry)},
            clear=True,
        ):
            claims = reviewer_qualification_claims(
                "backend_api_key", auth_source="api_key"
            )
        self.assertEqual(claims.qualifications, ())

    def test_unknown_qualification_fails_closed(self) -> None:
        registry = {"owner": {"qualifications": ["review.everything"]}}
        with patch.dict(
            os.environ,
            {"MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON": json.dumps(registry)},
            clear=True,
        ):
            with self.assertRaises(QualificationRegistryError) as ctx:
                reviewer_qualification_claims("owner", auth_source="owner_session")
        self.assertEqual(ctx.exception.code, "UNKNOWN_REVIEWER_QUALIFICATION")

    def test_expired_qualification_is_removed_by_existing_principal_resolver(self) -> None:
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        identity = AuthenticatedIdentity(
            subject_id="owner",
            authenticated=True,
            role_names=("ADMINISTRATOR",),
            qualifications=("qualified.science-reviewer",),
            qualification_expires_at={"qualified.science-reviewer": expired},
        )
        principal = PrincipalResolver().resolve(identity)
        self.assertEqual(principal.qualifications, ())

    def test_owner_session_dependency_receives_registry_claims(self) -> None:
        registry = {
            "owner": {
                "qualifications": ["qualified.science-reviewer"],
                "specialties": ["conservation"],
            }
        }
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", b"calyx_owner_session=test-token")],
        }
        request = Request(scope)
        with patch.dict(
            os.environ,
            {"MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON": json.dumps(registry)},
            clear=True,
        ), patch(
            "app.review_api.dependencies._decode_owner_token",
            return_value={"actor": "owner", "auth_type": "owner_session"},
        ):
            identity = _identity_from_owner_session(request)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.qualifications, ("qualified.science-reviewer",))
        self.assertEqual(identity.specialties, ("conservation",))


if __name__ == "__main__":
    unittest.main()
