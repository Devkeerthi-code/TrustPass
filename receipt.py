"""Signed compile receipts: who verified which circuits, with what result, and a commitment to the key.

A receipt holds SHA-256 hashes of the original, locked and returned circuits (as QASM 3), the
verdict and the numbers behind it, the backend and its calibration time, the TrustPass commit,
and key_commitment = SHA-256(salt || canonical JSON of the lock key). The salt and the key stay
in ~/.trustpass/keys; revealing both later lets anyone check the commitment (open_commitment).
sign() adds an Ed25519 signature over the canonical JSON (sorted keys, no spaces).

What it does not prove: that the compiler is honest (only the checks say that), or that the
verifier was. The signer is the verifier; the signature only binds them to what they reported.
"""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from qiskit import qasm3

from verify import FIDELITY_RATIO

ROOT = Path(__file__).parent


def home():
    """~/.trustpass, or $TRUSTPASS_HOME (tests point it at a temporary folder). Never inside the repo."""
    return Path(os.environ.get("TRUSTPASS_HOME") or Path.home() / ".trustpass")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def circuit_sha256(circ):
    return sha256(qasm3.dumps(circ))


def key_by_name(key):
    """Parameter -> float (or name -> float) as name -> float: the form that is stored and committed to."""
    return {getattr(p, "name", p): float(v) for p, v in key.items()}


def commitment(key, salt):
    return sha256(salt + canonical(key_by_name(key)).encode())


def save_key(locked, original, salt):
    """Store the key, salt and locked circuit locally, as keys/<sha256 of locked>.json."""
    locked_qasm = qasm3.dumps(locked.circuit)
    path = home() / "keys" / f"{sha256(locked_qasm)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"original_sha256": circuit_sha256(original), "locked_qasm": locked_qasm,
                                "key": key_by_name(locked.key), "salt": salt.hex(), "decoys": locked.decoys,
                                "created_utc": _now()}, indent=1), encoding="utf-8")
    return path


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _commit():
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty", "--abbrev=40"], cwd=ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _calibration(backend):
    try:
        return backend.properties().last_update_date.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return None


def make_receipt(original, locked, returned, report, backend, salt=None):
    """report: what the checks said, as pipeline.run returns it (functional, fidelity, trust).

    salt: the commitment salt stored with the key; if None a fresh one is drawn and the key is
    saved with it, so it can be opened later.
    """
    if salt is None:
        salt = os.urandom(32)
        save_key(locked, original, salt)
    fd = report["fidelity"]
    return {
        "circuits_sha256": {"original": circuit_sha256(original), "locked": circuit_sha256(locked.circuit),
                            "returned": circuit_sha256(returned)},
        "verdict": report["trust"]["verdict"],
        "qcec": report["functional"]["verdict"],
        "fidelity": {"esp": fd["esp"], "esp_baseline": fd["esp_baseline"], "ratio": fd["ratio"],
                     "threshold": FIDELITY_RATIO, "audit": fd["verdict"]},
        "backend": backend.name,
        "calibration_utc": _calibration(backend),
        "trustpass_commit": _commit(),
        "created_utc": _now(),
        "key_commitment": commitment(locked.key, salt),
    }


def keygen(public_path):
    """Make (or reuse) the signing key in ~/.trustpass/signing_key; write its public key to public_path."""
    private = home() / "signing_key"
    if private.exists():
        key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    else:
        private.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        os.chmod(private, 0o600)
    Path(public_path).write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                                serialization.PublicFormat.SubjectPublicKeyInfo))
    return Path(public_path)


def sign(receipt):
    key = serialization.load_pem_private_key((home() / "signing_key").read_bytes(), password=None)
    body = {k: v for k, v in receipt.items() if k != "signature"}
    return {**body, "signature": key.sign(canonical(body).encode()).hex()}


def verify_receipt(receipt, public_key):
    """public_key: an Ed25519PublicKey, PEM bytes or a path to a PEM file."""
    try:
        if not isinstance(public_key, Ed25519PublicKey):
            pem = public_key if isinstance(public_key, bytes) else Path(public_key).read_bytes()
            public_key = serialization.load_pem_public_key(pem)
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        body = {k: v for k, v in receipt.items() if k != "signature"}
        public_key.verify(bytes.fromhex(receipt["signature"]), canonical(body).encode())
        return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False


def open_commitment(receipt, key, salt):
    """Does the revealed key (+ salt, bytes or hex) match the receipt's commitment?"""
    salt = bytes.fromhex(salt) if isinstance(salt, str) else salt
    return commitment(key, salt) == receipt.get("key_commitment")
