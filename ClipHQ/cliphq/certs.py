"""Local HTTPS for the phone page.

iPhone only allows "Save Video" via the share menu (Web Share API) on secure (https) pages.
We make a private "Clip HQ Local CA" once, and a certificate for this laptop's Wi-Fi address.
You install the CA on your iPhone once (the phone page walks you through it).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket

from .config import DATA_DIR

CA_CERT = DATA_DIR / "cliphq-ca.crt"
CA_KEY = DATA_DIR / "cliphq-ca.key"
SRV_CERT = DATA_DIR / "server.crt"
SRV_KEY = DATA_DIR / "server.key"
SRV_IPS = DATA_DIR / "server_ips.txt"


def local_ips() -> list[str]:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    # prefer typical home Wi-Fi ranges first
    return sorted(ips, key=lambda ip: (not ip.startswith("192.168."), not ip.startswith("10."), ip))


def ensure_certs() -> tuple[str, str] | None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except Exception:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    if not CA_CERT.exists() or not CA_KEY.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Clip HQ Local CA"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Clip HQ (this laptop only)")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                             content_commitment=False, key_encipherment=False, data_encipherment=False,
                                             key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                .sign(key, hashes.SHA256()))
        CA_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                             serialization.NoEncryption()))
        CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        if SRV_CERT.exists():
            SRV_CERT.unlink()
    ips = local_ips()
    want = ",".join(ips)
    if SRV_CERT.exists() and SRV_KEY.exists() and SRV_IPS.exists() and SRV_IPS.read_text() == want:
        return str(SRV_CERT), str(SRV_KEY)
    ca_key = serialization.load_pem_private_key(CA_KEY.read_bytes(), None)
    ca = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    host = socket.gethostname()
    san = [x509.DNSName("localhost"), x509.DNSName(host), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ips[0] if ips else host)]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=397))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    SRV_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()))
    SRV_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    SRV_IPS.write_text(want)
    return str(SRV_CERT), str(SRV_KEY)
