from starlette.requests import Request
from starlette.responses import Response

from app.routers.orchid_widgets import _allow_frontend_origin


def _request(origin: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/media/genus/Cattleya",
            "headers": [(b"origin", origin.encode("utf-8"))],
        }
    )


def test_allowed_origin_gets_allow_credentials_true():
    # The frontend's shared fetch transport sends every Calyx-origin request
    # with credentials: 'include' (see backendConfig.ts), including calls to
    # these public, unauthenticated read endpoints. A live browser audit of
    # production confirmed the browser silently discards the whole response
    # when Access-Control-Allow-Credentials is missing, even though
    # Access-Control-Allow-Origin is set correctly — reproducing this here.
    response = Response()
    _allow_frontend_origin(_request("https://orchid-continuum-frontend-vof6.onrender.com"), response)

    assert response.headers["access-control-allow-origin"] == "https://orchid-continuum-frontend-vof6.onrender.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_disallowed_origin_gets_no_cors_headers():
    response = Response()
    _allow_frontend_origin(_request("https://evil.example.org"), response)

    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
