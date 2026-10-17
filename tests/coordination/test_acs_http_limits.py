import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler

from coordination.http_server import BoundedHTTPServer


class HTTPWorkerLimitsTests(unittest.TestCase):
    def test_slow_header_client_does_not_allow_unbounded_workers(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

        server = BoundedHTTPServer(("127.0.0.1", 0), Handler, max_workers=1)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        first = socket.create_connection(server.server_address, timeout=2)
        second = None
        try:
            first.sendall(b"GET / HTTP/1.1\r\n")
            # Deterministically wait until the first worker owns the sole slot.
            for _ in range(100):
                if not server._slots.acquire(blocking=False):
                    break
                server._slots.release()
                threading.Event().wait(0.005)
            else:
                self.fail("first worker did not claim its slot")
            second = socket.create_connection(server.server_address, timeout=2)
            second.settimeout(2)
            self.assertEqual(second.recv(1), b"")
        finally:
            first.close()
            if second:
                second.close()
            server.shutdown()
            server.server_close()
            worker.join()
