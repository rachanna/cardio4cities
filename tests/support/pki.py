"""A throwaway certificate authority for the certificate tests (BD-15): a root, an
intermediate, and server certificates signed by it, with an AIA URL pointing at where the
intermediate can be fetched. Fictional hosts (Halden Bay, Norvania) only."""

import datetime as dt
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

NOW = dt.datetime.now(dt.UTC)
Key = ec.EllipticCurvePrivateKey


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _key() -> Key:
    return ec.generate_private_key(ec.SECP256R1())


def _cert(
    subject: str,
    key: Key,
    issuer: str,
    issuer_key: Key,
    *,
    ca: bool,
    host: str | None = None,
    aia: str | None = None,
    days: tuple[int, int] = (-1, 30),
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + dt.timedelta(days=days[0]))
        .not_valid_after(NOW + dt.timedelta(days=days[1]))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        # Key identifiers, as real certificates carry them (the chain verifier requires them)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), False
        )
    )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), True
        )
    if host:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), False)
    if aia:
        builder = builder.add_extension(
            x509.AuthorityInformationAccess(
                [
                    x509.AccessDescription(
                        AuthorityInformationAccessOID.CA_ISSUERS,
                        x509.UniformResourceIdentifier(aia),
                    )
                ]
            ),
            False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


@dataclass
class Authority:
    root: x509.Certificate
    root_key: Key
    intermediate: x509.Certificate
    intermediate_key: Key

    def trusting(self) -> ssl.SSLContext:
        """A client context that trusts the root only, as a real trust store would."""
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=pem(self.root).decode("ascii"))
        return context

    def server(
        self,
        folder: Path,
        host: str,
        *,
        aia: str | None = None,
        expired: bool = False,
        self_signed: bool = False,
        chain: bool = False,
        by_root: bool = False,
    ) -> ssl.SSLContext:
        """A server context for `host`, sending only its own certificate unless `chain`.
        `by_root`: issued directly by this authority's root, with no intermediate."""
        key = _key()
        if self_signed:
            cert = _cert(host, key, host, key, ca=False, host=host)
        else:
            days = (-30, -1) if expired else (-1, 30)
            issuer, issuer_key = (
                (self.root.subject.rfc4514_string()[3:], self.root_key)
                if by_root
                else ("Norvania Test Issuing CA", self.intermediate_key)
            )
            cert = _cert(
                host, key, issuer, issuer_key, ca=False, host=host, aia=aia, days=days,
            )  # fmt: skip
        body = pem(cert) + (pem(self.intermediate) if chain else b"")
        cert_file, key_file = folder / f"{host}.pem", folder / f"{host}.key"
        cert_file.write_bytes(body)
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(cert_file, key_file)
        return context


def authority() -> Authority:
    root_key, intermediate_key = _key(), _key()
    root = _cert("Norvania Test Root", root_key, "Norvania Test Root", root_key, ca=True)
    intermediate = _cert(
        "Norvania Test Issuing CA", intermediate_key, "Norvania Test Root", root_key, ca=True
    )
    return Authority(root, root_key, intermediate, intermediate_key)
