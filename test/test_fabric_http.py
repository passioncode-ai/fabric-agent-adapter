"""FAA-65 REQ-06: fabric_http, on the cases fabric-http.mjs reads too (test/fixtures/kit-http-cases.json), plus the
default transport against a server on loopback (no test leaves this machine)."""
import http.server
import json
import threading
import unittest
from pathlib import Path

from test_fabric_service import load  # noqa: E402

fh = load("fabric_http")

CASES = json.loads((Path(__file__).parent / "fixtures/kit-http-cases.json").read_text(encoding="utf-8"))


def scripted(steps, seen):
    steps = list(steps)

    def transport(method, url, headers, body, timeout_s, max_bytes):
        seen.append({"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout_s})
        step = steps.pop(0)
        if step.get("error") == "connection":
            raise ConnectionResetError("reset")
        if step.get("error") == "timeout":
            raise TimeoutError("slow")
        return step["status"], step.get("headers", {}), step.get("body", "").encode("utf-8")
    return transport


def run(case, seen=None, **extra):
    seen = [] if seen is None else seen
    sleeps, now = [], [0.0]

    def sleep(s):
        sleeps.append(s)
        now[0] += s
    kwargs = dict(headers=case.get("headers"), body=case.get("body"), retries=case.get("retries", 2),
                  deadline_s=case.get("deadlineS", 30), max_bytes=case.get("maxBytes", fh.DEFAULT_MAX_BYTES),
                  max_retry_after_s=case.get("maxRetryAfterS", 30), transport=scripted(case["steps"], seen),
                  sleep=sleep, clock=lambda: now[0], rand=lambda: 0.5)
    kwargs.update(extra)
    try:
        answer = fh.request(case["method"], case.get("url", "https://api.example/v1/items"), **kwargs)
        return {"status": answer.status, "attempts": answer.attempts, "sleeps": sleeps}
    except fh.HttpError as err:
        return {"error": err.kind, "attempts": err.attempts, "sleeps": sleeps, "message": str(err)}


class Cases(unittest.TestCase):
    def test_redact(self):
        for url, expected in CASES["redact"]:
            self.assertEqual(fh.redact_url(url), expected, url)

    def test_check_url(self):
        for url, insecure, refused in CASES["checkUrl"]:
            with self.subTest(url=url):
                if refused:
                    with self.assertRaises(fh.HttpError) as caught:
                        fh.check_url(url, insecure=insecure)
                    self.assertEqual(caught.exception.kind, "refused")
                    self.assertNotIn("pass@", str(caught.exception) + caught.exception.url)
                else:
                    fh.check_url(url, insecure=insecure)

    def test_check_url_refuses_an_authority_it_would_send_elsewhere_than_it_logs(self):
        # 0.56.0 seam r12: urllib sends `https://api.example\v1/items` to host `api.example\v1` while redact_url, read
        # as WHATWG reads it, logs `https://api.example/v1/items`. Python refuses it; the Node twin sends it to
        # api.example, so this case is the Python twin's own and not a shared vector.
        # 0.56.0 product r16: a tab or line break, which urlsplit drops and urllib sends (http.client refuses it).
        for url in ("https://api.example\\v1/items", "https://h.example\\/x", "https://h .example/x",
                    "https://h.exa\tmple/x", "http://127.0.0.\t1:9/x", "https://h.example/x\n"):
            with self.subTest(url=url), self.assertRaises(fh.HttpError) as caught:
                fh.check_url(url)
            self.assertEqual(caught.exception.kind, "refused")

    def test_retry_after(self):
        for value, now, expected in CASES["retryAfter"]:
            self.assertEqual(fh.retry_after_s(value, now=now), expected, value)

    def test_may_retry_and_backoff(self):
        for method, headers, status, expected in CASES["mayRetry"]:
            self.assertEqual(fh.may_retry(method, headers, status), expected, (method, headers, status))
        for attempt, base, cap, rand, expected in CASES["backoff"]:
            self.assertEqual(fh.backoff_s(attempt, base_s=base, max_s=cap, rand=rand), expected)

    def test_bodies(self):
        for value, text in CASES["jsonBody"]:
            self.assertEqual(fh.json_bytes(value), text.encode("utf-8"))
        for value, text in CASES["textBody"]:
            self.assertEqual(fh.utf8(value), text.encode("utf-8"))
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(fh.HttpError) as caught:
                fh.request("POST", "https://api.example/", body={"n": bad}, transport=scripted([], []))
            self.assertEqual(caught.exception.kind, "refused")

    def test_scenarios(self):
        for case in CASES["scenarios"]:
            with self.subTest(case["name"]):
                got = run(case)
                got.pop("message", None)
                self.assertEqual(got, case["expect"])


class Rules(unittest.TestCase):
    def test_no_secret_in_an_error(self):
        case = {"method": "GET", "url": "https://api.example/v1?api_key=sk-or-v1-SECRET",
                "headers": {"Authorization": "Bearer sk-or-v1-SECRET"}, "retries": 0, "steps": [{"error": "connection"}]}
        got = run(case)
        self.assertEqual(got["error"], "connection")
        self.assertNotIn("SECRET", got["message"])
        self.assertIn("https://api.example/v1", got["message"])

    def test_one_deadline_across_attempts(self):
        seen = []
        run({"method": "GET", "deadlineS": 10, "retries": 3, "steps": [{"status": 503}, {"status": 503}, {"status": 200}]},
            seen)
        self.assertEqual([round(s["timeout"], 3) for s in seen], [10, 9.5, 8.5])

    def test_a_json_body_is_sent_as_json(self):
        seen = []
        run({"method": "POST", "body": {"q": "é"}, "steps": [{"status": 200}]}, seen)
        self.assertEqual(seen[0]["body"], '{"q":"é"}'.encode("utf-8"))
        self.assertEqual(seen[0]["headers"]["Content-Type"], "application/json")
        seen = []
        run({"method": "POST", "body": {"q": 1}, "headers": {"content-type": "application/vnd.x+json"},
             "steps": [{"status": 200}]}, seen)
        self.assertNotIn("Content-Type", seen[0]["headers"])

    def test_header_injection_is_refused(self):
        for headers in ({"X-A": "1\r\nX-B: 2"}, {"Bad Name": "1"}, {"X-A": "a\0"}):
            with self.assertRaises(fh.HttpError):
                fh.request("GET", "https://api.example/", headers=headers, transport=scripted([], []))

    def test_bad_arguments(self):
        for kwargs in ({"retries": -1}, {"retries": 11}, {"retries": True}, {"deadline_s": 0}, {"max_bytes": 0}):
            with self.assertRaises(fh.HttpError, msg=kwargs):
                fh.request("GET", "https://api.example/", transport=scripted([], []), **kwargs)
        with self.assertRaises(fh.HttpError):
            fh.request("G ET", "https://api.example/", transport=scripted([], []))

    def test_response_helpers(self):
        answer = fh.Response(200, {"Content-Type": "application/json"}, b'{"a":[1]}')
        self.assertTrue(answer.ok)
        self.assertEqual(answer.headers["content-type"], "application/json")
        self.assertEqual(answer.json(), {"a": [1]})


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"x" * 100)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/missing":
            self.send_response(404)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"no")
        else:
            body = json.dumps({"auth": self.headers.get("Authorization")}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


class DefaultTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_answers_redirects_and_caps(self):
        ok = fh.request("GET", self.base + "/ok", headers={"Authorization": "Bearer t"}, deadline_s=10)
        self.assertEqual(ok.json(), {"auth": "Bearer t"})
        self.assertEqual(fh.request("GET", self.base + "/missing", deadline_s=10).status, 404)
        moved = fh.request("GET", self.base + "/redirect", deadline_s=10, retries=0)
        self.assertEqual(moved.status, 302, "a redirect is answered, never followed")
        with self.assertRaises(fh.HttpError) as caught:
            fh.request("GET", self.base + "/big", deadline_s=10, max_bytes=10)
        self.assertEqual(caught.exception.kind, "too-large")

    # FAA-72 item 25: these three ran against margins of 0.5 to 0.8 s and flaked under load. Each now pits the deadline
    # against a server that would hold the caller far longer (a byte every 0.2 s for a minute), so the upper bound can
    # be generous (DEADLINE_SLACK) and still tell a whole-answer deadline from one a read or the headers restart.
    DEADLINE_SLACK = 6.0

    def serve(self, script):
        """A one-connection server running `script(conn, stop)`; returns its URL. The server ends with the test."""
        import socket
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        stop = threading.Event()
        self.addCleanup(server.close)
        self.addCleanup(stop.set)

        def run():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            try:
                conn.recv(65536)
                script(conn, stop)
            except OSError:
                pass
            finally:
                conn.close()
        threading.Thread(target=run, daemon=True).start()
        return "http://127.0.0.1:%d/" % server.getsockname()[1]

    @staticmethod
    def trickle(conn, stop, data, every=0.2):
        for byte in data:
            if stop.wait(every):
                return
            conn.sendall(bytes([byte]))

    def timed_out_within(self, url, deadline_s, bound_s):
        import time as _time
        start = _time.monotonic()
        with self.assertRaises(fh.HttpError) as caught:
            fh.request("GET", url, deadline_s=deadline_s, retries=0)
        elapsed = _time.monotonic() - start
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertLess(elapsed, bound_s)
        return elapsed

    def test_a_trickled_body_stops_at_the_deadline(self):
        url = self.serve(lambda conn, stop: (conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n"),
                                             self.trickle(conn, stop, b"x" * 300)))
        # A per-read timeout would let this run for the minute the server trickles.
        self.timed_out_within(url, 2, 2 + self.DEADLINE_SLACK)

    def test_slow_headers_count_toward_the_deadline(self):
        def slow(conn, stop):
            if stop.wait(3.9):
                return
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n")
            self.trickle(conn, stop, b"x" * 300)
        # Headers at 3.9 s of a 4 s deadline: a deadline that restarted with the body would end near 7.9 s.
        self.timed_out_within(self.serve(slow), 4, 4 + 2.5)

    def test_trickled_headers_stop_at_the_deadline(self):
        url = self.serve(lambda conn, stop: self.trickle(conn, stop, b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 300))
        self.timed_out_within(url, 2, 2 + self.DEADLINE_SLACK)

    def test_json_is_read_as_json_parse_reads_it(self):
        self.assertEqual(fh.Response(200, {}, b"\xef\xbb\xbf{\"a\":1}").json(), {"a": 1})
        for bad in (b'{"a":NaN}', b"[" * 200000 + b"]" * 200000, b"Infinity"):
            with self.assertRaises(ValueError):
                fh.Response(200, {}, bad).json()

    def test_a_transport_bug_is_a_connection_error_as_in_node(self):
        def broken(*args):
            raise RuntimeError("bug")
        with self.assertRaises(fh.HttpError) as caught:
            fh.request("GET", "https://api.example/", transport=broken, retries=0)
        self.assertEqual(caught.exception.kind, "connection")

    def test_a_closed_port_is_a_connection_error(self):
        with self.assertRaises(fh.HttpError) as caught:
            fh.request("GET", "http://127.0.0.1:1/", deadline_s=5, retries=0)
        self.assertEqual(caught.exception.kind, "connection")


if __name__ == "__main__":
    unittest.main()
