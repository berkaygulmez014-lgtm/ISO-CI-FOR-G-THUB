"""Ed25519 helpers shared by the hard-deny oracle, the approval gate and sysapply.

One rule drove the split: a verifier must never hold a signing key. Everything here
works on raw 32-byte public / 64-byte secret keys (libsodium layout), with a
`cryptography` fallback when libsodium is absent.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import os

from . import util


class CryptoError(RuntimeError):
    pass


def _backend():
    """Return ("sodium", lib) | ("cryptography", None) | ("openssl", path)."""
    name = ctypes.util.find_library("sodium")
    if name:
        try:
            lib = ctypes.CDLL(name)
            lib.crypto_sign_keypair.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            lib.crypto_sign_seed_keypair.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                                     ctypes.c_char_p]
            lib.crypto_sign_detached.argtypes = [ctypes.c_char_p, ctypes.c_void_p,
                                                 ctypes.c_char_p, ctypes.c_ulonglong,
                                                 ctypes.c_char_p]
            lib.crypto_sign_verify_detached.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                                        ctypes.c_ulonglong, ctypes.c_char_p]
            return "sodium", lib
        except (OSError, AttributeError):
            pass
    try:
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401

        return "cryptography", None
    except ImportError:
        pass
    import shutil

    openssl = shutil.which("openssl")
    if openssl:
        return "openssl", openssl
    raise CryptoError("no Ed25519 backend available (libsodium, python cryptography "
                      "or openssl required)")


def public_from_secret(secret: bytes) -> bytes:
    kind, lib = _backend()
    if kind == "sodium":
        pk = ctypes.create_string_buffer(32)
        sk = ctypes.create_string_buffer(64)
        if lib.crypto_sign_seed_keypair(pk, sk, secret[:32]) != 0:
            raise CryptoError("cannot derive public key from secret")
        return bytes(pk.raw)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(secret[:32]).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def keygen(sk_path: str, pub_path: str) -> tuple[bytes, bytes]:
    kind, lib = _backend()
    if kind == "sodium":
        pk = ctypes.create_string_buffer(32)
        sk = ctypes.create_string_buffer(64)
        if lib.crypto_sign_keypair(pk, sk) != 0:
            raise CryptoError("libsodium keypair generation failed")
        secret, public = bytes(sk.raw), bytes(pk.raw)
    elif kind == "cryptography":
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(serialization.Encoding.Raw,
                                 serialization.PrivateFormat.Raw,
                                 serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
        secret = seed + public
    else:
        raise CryptoError("openssl-only backend cannot generate keys")
    util.atomic_write(sk_path, secret, mode=0o600)
    util.atomic_write(pub_path, public, mode=0o644)
    return secret, public


def sign(message: bytes, secret: bytes) -> bytes:
    if len(secret) not in (32, 64):
        raise CryptoError("ed25519 secret key must be 32 or 64 bytes")
    kind, lib = _backend()
    if kind == "sodium":
        sk = secret if len(secret) == 64 else secret + b"\x00" * 32
        signature = ctypes.create_string_buffer(64)
        length = ctypes.c_ulonglong(0)
        if lib.crypto_sign_detached(signature, ctypes.byref(length), message,
                                    len(message), sk) != 0:
            raise CryptoError("ed25519 signing failed")
        return bytes(signature.raw)
    if kind == "cryptography":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        return Ed25519PrivateKey.from_private_bytes(secret[:32]).sign(message)
    raise CryptoError("openssl-only backend cannot sign")


def verify(message: bytes, signature: bytes, public: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    kind, lib = _backend()
    if kind == "sodium":
        return lib.crypto_sign_verify_detached(signature, message, len(message), public) == 0
    if kind == "cryptography":
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
            return True
        except (InvalidSignature, ValueError):
            return False
    return False


def load_secret(path: str) -> bytes:
    if not os.path.exists(path):
        raise CryptoError(f"signing key not found: {path}")
    with open(path, "rb") as handle:
        secret = handle.read()
    if len(secret) not in (32, 64):
        raise CryptoError(f"signing key at {path} has wrong size ({len(secret)})")
    return secret


def load_public(path: str) -> bytes:
    if not os.path.exists(path):
        raise CryptoError(f"public key not found: {path}")
    with open(path, "rb") as handle:
        public = handle.read()
    if len(public) != 32:
        raise CryptoError(f"public key at {path} has wrong size ({len(public)})")
    return public


def key_id(public: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public).hexdigest()[:16]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    """Accept "base64:…", "ed25519:…" or bare base64 — a scheme prefix is metadata,
    not payload. Stripping only "base64:" silently decoded the prefix as data."""
    raw = text.strip()
    if raw.startswith("base64:"):
        raw = raw[len("base64:"):]
    elif ":" in raw:
        raw = raw.split(":", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise CryptoError(f"bad base64 payload: {exc}") from exc
