import unittest

from server import allowed_host, allowed_origin


class LanAccessTests(unittest.TestCase):
    def test_lan_and_explicit_localhost_hosts(self):
        port = 8765
        self.assertTrue(allowed_host("127.0.0.1:8765", "127.0.0.1", port))
        self.assertTrue(allowed_host("localhost:8765", "127.0.0.1", port))
        self.assertFalse(allowed_host("192.168.1.20:8765", "127.0.0.1", port))

        for host in ("localhost", "127.0.0.1", "192.168.1.20", "10.3.4.5", "172.20.0.8"):
            with self.subTest(host=host):
                self.assertTrue(allowed_host(f"{host}:8765", "0.0.0.0", port))

        for host in (
            "evil.example:8765", "8.8.8.8:8765", "0.0.0.0:8765",
            "192.168.1.20:8766", "192.168.1.20", "192.168.1.999:8765",
        ):
            with self.subTest(host=host):
                self.assertFalse(allowed_host(host, "0.0.0.0", port))

    def test_origin_must_match_browser_address(self):
        host = "192.168.1.20:8765"
        self.assertTrue(allowed_origin(f"http://{host}", host))
        self.assertTrue(allowed_origin("", host))
        self.assertFalse(allowed_origin("http://192.168.1.21:8765", host))
        self.assertFalse(allowed_origin("https://192.168.1.20:8765", host))


if __name__ == "__main__":
    unittest.main()
