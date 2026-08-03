from fastapi import Response
from starlette.requests import Request

from app.routers import orchid_widgets


class FakeCursor:
    closed = False

    def close(self):
        self.closed = True


class FakeRawConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class FakeEngine:
    def __init__(self, raw):
        self.raw = raw

    def raw_connection(self):
        return self.raw


def request(origin: str = "https://orchidcontinuum.org") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/platform/readiness/homepage",
            "headers": [(b"origin", origin.encode("utf-8"))],
        }
    )


def test_homepage_readiness_uses_live_cursor_and_closes_resources(monkeypatch):
    raw = FakeRawConnection()
    expected = {
        "contract": "calyx-live-graph-audit-v1",
        "homepage_ready": False,
        "blockers": ["taxonomy_image_graph_edges_absent"],
    }

    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: FakeEngine(raw))
    monkeypatch.setattr(
        orchid_widgets,
        "run_live_graph_audit",
        lambda cursor: expected if cursor is raw.cursor_instance else None,
    )

    response = Response()
    result = orchid_widgets.homepage_readiness(request(), response)

    assert result == expected
    assert response.headers["access-control-allow-origin"] == "https://orchidcontinuum.org"
    assert raw.cursor_instance.closed is True
    assert raw.closed is True


def test_canonical_readiness_route_is_registered():
    paths = {route.path for route in orchid_widgets.router.routes}
    assert "/api/platform/readiness/homepage" in paths
