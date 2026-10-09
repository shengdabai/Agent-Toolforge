import io
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fetchers


def address(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.destination = None
        self.sent = []

    def settimeout(self, value):
        pass

    def connect(self, destination):
        self.destination = destination

    def sendall(self, data):
        self.sent.append(data)

    def makefile(self, *args):
        return io.BytesIO(self.response)

    def close(self):
        pass


class NetworkBoundary(unittest.TestCase):
    def test_private_destinations_never_connect(self):
        for ip in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "224.0.0.1", "::1", "fc00::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1"]:
            with self.subTest(ip=ip), patch.object(socket, "getaddrinfo", return_value=address(ip)), patch.object(socket, "socket") as connect:
                self.assertIsNone(fetchers.http_fetcher("https://fixture.test/"))
                connect.assert_not_called()

    def test_invalid_and_credentials_rejected_before_dns(self):
        for url in ["file:///etc/passwd", "https://user:pass@example.test", "http://x/\r\nX:1", "https://[fe80::1%lo0]/"]:
            with patch.object(socket, "getaddrinfo") as dns:
                self.assertIsNone(fetchers.http_fetcher(url))
                dns.assert_not_called()

    def test_mixed_dns_rejected(self):
        with patch.object(socket, "getaddrinfo", return_value=address("8.8.8.8") + address("10.0.0.1")), patch.object(socket, "socket") as connect:
            self.assertIsNone(fetchers.http_fetcher("http://fixture.test"))
            connect.assert_not_called()

    def test_pinned_socket_and_tls_hostname(self):
        fake = FakeSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        tls = Mock()
        tls.wrap_socket.return_value = fake
        with patch.object(socket, "getaddrinfo", return_value=address("8.8.8.8")) as dns, patch.object(socket, "socket", return_value=fake), patch.object(fetchers.ssl, "create_default_context", return_value=tls):
            self.assertEqual(fetchers.http_fetcher("https://fixture.test/path?q=1"), 200)
            self.assertEqual(dns.call_count, 1)
            self.assertEqual(fake.destination, ("8.8.8.8", 443))
            tls.wrap_socket.assert_called_once_with(fake, server_hostname="fixture.test")
            self.assertIn(b"HEAD /path?q=1 HTTP/1.1", b"".join(fake.sent))
            self.assertIn(b"Host: fixture.test", b"".join(fake.sent))

    def test_redirect_to_private_rejected(self):
        fake = FakeSocket(b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n")
        with patch.object(socket, "getaddrinfo", side_effect=[address("8.8.8.8"), address("127.0.0.1")]), patch.object(socket, "socket", return_value=fake) as connect:
            self.assertIsNone(fetchers.http_fetcher("http://fixture.test"))
            self.assertEqual(connect.call_count, 1)

    def test_head_falls_back_for_method_rejection(self):
        with patch.object(fetchers, "_request", side_effect=[(405, b""), (200, b"")]) as request:
            self.assertEqual(fetchers.http_fetcher("https://fixture.test"), 200)
            self.assertEqual([x.args[1] for x in request.call_args_list], ["HEAD", "GET"])

    def test_private_url_not_sent_to_archive(self):
        with patch.object(socket, "getaddrinfo", return_value=address("10.0.0.1")), patch.object(fetchers, "_request") as request:
            self.assertIsNone(fetchers.wayback_fetcher("http://internal.test/private"))
            request.assert_not_called()

    def test_archive_bad_json_shape(self):
        with patch.object(fetchers, "_public_target"), patch.object(fetchers, "_request", return_value=(200, b"[]")):
            self.assertIsNone(fetchers.wayback_fetcher("https://fixture.test"))

    def test_archive_query_never_sent_and_fragment_removed(self):
        with patch.object(fetchers, "_public_target"), patch.object(fetchers, "_request", return_value=(200, b"{}")) as request:
            self.assertIsNone(fetchers.wayback_fetcher("https://fixture.test/reset?token=synthetic#private"))
            request.assert_not_called()
            self.assertEqual(fetchers.wayback_fetcher("https://fixture.test/article#private"), 404)
            self.assertNotIn("private", request.call_args.args[0])
            self.assertNotIn("%23", request.call_args.args[0])

    def test_exhausted_budget_does_not_start_archive(self):
        with patch.object(fetchers.time, "monotonic", side_effect=[0, 10]), patch.object(fetchers, "http_fetcher", return_value=None), patch.object(fetchers, "wayback_fetcher") as archive:
            self.assertIsNone(fetchers.resilient_fetcher("https://fixture.test", timeout=8))
            archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
