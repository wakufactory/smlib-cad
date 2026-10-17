import subprocess
import plistlib
import tempfile
import unittest
from pathlib import Path

from local_cert import ensure_certificates


class LocalCertificateTests(unittest.TestCase):
    def test_ca_and_server_certificate_cover_lan_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            ensure_certificates(path, ["192.168.1.88"])
            ca = path / "local-ca.crt"
            server = path / "server.crt"
            profile = plistlib.loads((path / "local-ca.mobileconfig").read_bytes())
            self.assertEqual(profile["PayloadContent"][0]["PayloadType"], "com.apple.security.root")
            self.assertTrue((path / "local-ca.key").exists())
            self.assertEqual(subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(server)],
                                            capture_output=True).returncode, 0)
            details = subprocess.run(["openssl", "x509", "-in", str(server), "-noout",
                                      "-ext", "subjectAltName"], capture_output=True, text=True, check=True).stdout
            self.assertIn("DNS:localhost", details)
            self.assertIn("IP Address:192.168.1.88", details)
            original_ca = ca.read_bytes()
            ensure_certificates(path, ["192.168.1.89"])
            self.assertEqual(ca.read_bytes(), original_ca)
            renewed = subprocess.run(["openssl", "x509", "-in", str(server), "-noout",
                                      "-ext", "subjectAltName"], capture_output=True, text=True, check=True).stdout
            self.assertIn("IP Address:192.168.1.89", renewed)


if __name__ == "__main__":
    unittest.main()
