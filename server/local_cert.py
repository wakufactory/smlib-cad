"""Create a local CA and an HTTPS certificate for this Mac's current IPv4 addresses."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import plistlib
import re
import subprocess
import tempfile
import uuid
from pathlib import Path


def local_ips(extra_ips: list[str]) -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        output = subprocess.run(["ifconfig"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        output = ""
    for value in re.findall(r"\binet\s+(\d+(?:\.\d+){3})\b", output) + extra_ips:
        address = ipaddress.IPv4Address(value)
        if not (address.is_unspecified or address.is_multicast or address.is_reserved):
            addresses.add(str(address))
    return sorted(addresses, key=lambda value: int(ipaddress.IPv4Address(value)))


def openssl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["openssl", *args], check=True, capture_output=True, text=True)


def write_install_profile(directory: Path, ca_cert: Path) -> None:
    certificate = subprocess.run(["openssl", "x509", "-in", str(ca_cert), "-outform", "DER"],
                                 check=True, capture_output=True).stdout
    fingerprint = hashlib.sha256(certificate).hexdigest()
    identifier = f"local.smlib-modeler.ca.{fingerprint[:16]}"
    profile = {
        "PayloadContent": [{
            "PayloadCertificateFileName": "SMLib Modeler Local CA.cer",
            "PayloadContent": certificate,
            "PayloadDisplayName": "SMLib Modeler Local CA",
            "PayloadIdentifier": identifier + ".certificate",
            "PayloadType": "com.apple.security.root",
            "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, identifier + ".certificate")).upper(),
            "PayloadVersion": 1,
        }],
        "PayloadDisplayName": "SMLib Modeler Local CA",
        "PayloadIdentifier": identifier,
        "PayloadOrganization": "SMLib Modeler local development",
        "PayloadType": "Configuration",
        "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, identifier)).upper(),
        "PayloadVersion": 1,
    }
    (directory / "local-ca.mobileconfig").write_bytes(plistlib.dumps(profile))


def ensure_certificates(directory: Path, extra_ips: list[str]) -> list[str]:
    old_umask = os.umask(0o077)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        ca_cert, ca_key = directory / "local-ca.crt", directory / "local-ca.key"
        server_cert, server_key = directory / "server.crt", directory / "server.key"
        if ca_cert.exists() != ca_key.exists():
            raise RuntimeError("local CA certificate and key must both exist or both be absent")
        if not ca_cert.exists():
            openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
                    "-days", "3650", "-subj", "/CN=SMLib Modeler Local CA",
                    "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                    "-keyout", str(ca_key), "-out", str(ca_cert))
        write_install_profile(directory, ca_cert)
        ips = local_ips(extra_ips)
        if server_cert.exists() and server_key.exists():
            result = subprocess.run(["openssl", "x509", "-in", str(server_cert), "-noout",
                                     "-checkend", "86400", "-ext", "subjectAltName"],
                                    capture_output=True, text=True)
            verified = subprocess.run(["openssl", "verify", "-CAfile", str(ca_cert), str(server_cert)],
                                      capture_output=True, text=True)
            if (result.returncode == 0 and verified.returncode == 0 and
                    all(f"IP Address:{ip}" in result.stdout for ip in ips)):
                return ips
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            csr = Path(temporary) / "server.csr"
            config = Path(temporary) / "server.ext"
            config.write_text("[server_cert]\n"
                              "basicConstraints=critical,CA:FALSE\n"
                              "keyUsage=critical,digitalSignature,keyEncipherment\n"
                              "extendedKeyUsage=serverAuth\n"
                              "subjectAltName=@alt_names\n"
                              "[alt_names]\nDNS.1=localhost\n" +
                              "".join(f"IP.{index}={ip}\n" for index, ip in enumerate(ips, 1)))
            openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
                    "-subj", "/CN=localhost", "-keyout", str(server_key), "-out", str(csr))
            openssl("x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
                    "-CAcreateserial", "-days", "365", "-sha256", "-extfile", str(config),
                    "-extensions", "server_cert", "-out", str(server_cert))
        return ips
    finally:
        os.umask(old_umask)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path(".certs"))
    parser.add_argument("--ip", action="append", default=[], help="additional IPv4 address to include in the certificate")
    args = parser.parse_args()
    try:
        ips = ensure_certificates(args.dir, args.ip)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"certificate generation failed: {exc}\n")
    print(f"HTTPS certificate: {args.dir / 'server.crt'} (localhost, {', '.join(ips)})")
    print(f"Trust this CA on each client device: {args.dir / 'local-ca.crt'}")
    print(f"Apple device installation profile: {args.dir / 'local-ca.mobileconfig'}")


if __name__ == "__main__":
    main()
