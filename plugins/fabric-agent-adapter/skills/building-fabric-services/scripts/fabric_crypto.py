"""The kit's cryptography, once (FAA-65, layer L1): what the contract's verifiers need and nothing more.

- ``ed25519_verify(public_key, message, signature)`` (RFC 8032) and ``is_small_order_key`` with
  ``SMALL_ORDER_ENCODINGS``: a key of small order verifies forged signatures and is refused (DEC-0045).
- ``is_valid_p256_key`` and ``es256_verify`` (ECDSA P-256 over SHA-256, the signature in DER) for passkeys.
- ``ed25519_sign`` and ``ed25519_seed_public_key`` (RFC 8032), which ``fabric_package`` signs with, over ``ed_mul_secret``.
- base64url without padding (``b64url``, ``b64url_bytes``, ``node_base64``) and ``sha256``.

Pure Python over integers, slow next to OpenSSL. Verification multiplies public values only and takes the short path;
a secret scalar goes through ``ed_mul_secret``, a ladder that runs the same 256 steps whatever its bits are (FAA-78,
finding 45). Python's integers do not promise constant-time arithmetic, so that removes the branch on the secret, not
every timing difference: the signer stays a local, one-shot command line, never a service that signs for others.
Standard library only; imports no other kit module.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Optional, Tuple


# The small-order points of edwards25519 and their non-canonical encodings, sign bit cleared (the contract's
# src/ed25519.ts; libsodium's has_small_order list).
SMALL_ORDER_ENCODINGS = (
    "0000000000000000000000000000000000000000000000000000000000000000", "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05", "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)


def is_small_order_key(raw: bytes) -> bool:
    """Whether a 32-byte Ed25519 public key is a point of small order, in any encoding (CT-29)."""
    if len(raw) != 32:
        return True
    return (raw[:31] + bytes([raw[31] & 0x7F])).hex() in SMALL_ORDER_ENCODINGS


_ED_P = 2 ** 255 - 19


_ED_L = 2 ** 252 + 27742317777372353535851937790883648493


_ED_D = (-121665 * pow(121666, _ED_P - 2, _ED_P)) % _ED_P


_ED_SQRT_M1 = pow(2, (_ED_P - 1) // 4, _ED_P)


def _ed_add(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _ED_P
    bb = (y1 + x1) * (y2 + x2) % _ED_P
    cc = 2 * t1 * t2 * _ED_D % _ED_P
    dd = 2 * z1 * z2 % _ED_P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _ED_P, g * h % _ED_P, f * g % _ED_P, e * h % _ED_P)


def _ed_mul(scalar: int, point: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _ed_add(result, point)
        point = _ed_add(point, point)
        scalar >>= 1
    return result


def _ed_cswap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int], bit: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    """``(b, a)`` when ``bit`` is 1, ``(a, b)`` when it is 0, by arithmetic rather than a branch on ``bit``."""
    deltas = [(x - y) * bit for x, y in zip(a, b)]
    return (tuple(x - d for x, d in zip(a, deltas)), tuple(y + d for y, d in zip(b, deltas)))  # type: ignore[return-value]


def ed_mul_secret(scalar: int, point: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """``[scalar]point`` for a secret scalar below 2**256: a Montgomery ladder over all 256 bits with a conditional
    swap, so every scalar takes one addition and one doubling per bit and no step depends on a bit (finding 45). The
    addition law is complete on edwards25519, so the ladder needs no special case for the identity or a doubling."""
    r0, r1 = (0, 1, 1, 0), point
    for i in range(255, -1, -1):
        bit = (scalar >> i) & 1
        r0, r1 = _ed_cswap(r0, r1, bit)
        r1 = _ed_add(r0, r1)
        r0 = _ed_add(r0, r0)
        r0, r1 = _ed_cswap(r0, r1, bit)
    return r0


def _secret_scalar(seed: bytes) -> Tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_seed_public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte Ed25519 seed (RFC 8032 §5.1.5)."""
    return _ed_encode_point(ed_mul_secret(_secret_scalar(seed)[0], _ED_G))


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    """A deterministic Ed25519 signature (RFC 8032 §5.1.6); the same seed and message give the bytes Node's crypto.sign
    gives. Both secret multiplications (the key's scalar, the nonce) go through ``ed_mul_secret``."""
    a, prefix = _secret_scalar(seed)
    public = _ed_encode_point(ed_mul_secret(a, _ED_G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _ED_L
    big_r = _ed_encode_point(ed_mul_secret(r, _ED_G))
    k = int.from_bytes(hashlib.sha512(big_r + public + message).digest(), "little") % _ED_L
    return big_r + ((r + k * a) % _ED_L).to_bytes(32, "little")


def _ed_decode_point(data: bytes) -> Optional[Tuple[int, int, int, int]]:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _ED_P:
        return None
    x2 = (y * y - 1) * pow(_ED_D * y * y + 1, _ED_P - 2, _ED_P) % _ED_P
    if x2 == 0:
        if sign:
            return None
        return (0, y, 1, 0)
    x = pow(x2, (_ED_P + 3) // 8, _ED_P)
    if (x * x - x2) % _ED_P:
        x = x * _ED_SQRT_M1 % _ED_P
    if (x * x - x2) % _ED_P:
        return None
    if x & 1 != sign:
        x = _ED_P - x
    return (x, y, 1, x * y % _ED_P)


def _ed_encode_point(point: Tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = point
    zi = pow(z, _ED_P - 2, _ED_P)
    x, y = x * zi % _ED_P, y * zi % _ED_P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


_ED_G = _ed_decode_point(bytes.fromhex("5866666666666666666666666666666666666666666666666666666666666666"))


_ED_IDENTITY = (1).to_bytes(32, "little")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7, cofactorless: [S]B == R + [k]A, compared by R's encoding. False, never an exception."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _ED_L:
        return False
    a = _ed_decode_point(public_key)
    if a is None or _ed_encode_point(_ed_mul(8, a)) == _ED_IDENTITY:
        return False  # a small-order key would accept R = [S]B for a quarter or more of all messages; OpenSSL refuses it
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _ED_L
    neg_a = ((-a[0]) % _ED_P, a[1], a[2], (-a[3]) % _ED_P)
    return secrets.compare_digest(_ed_encode_point(_ed_add(_ed_mul(s, _ED_G), _ed_mul(k, neg_a))), signature[:32])


def b64url_bytes(text: str) -> bytes:
    """Buffer.from(text, "base64url") for text of the base64url alphabet: a dangling sixth bit group is ignored."""
    return b64url_decode(text)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def node_base64(text: str) -> bytes:
    """Buffer.from(text, "base64"): either alphabet, other characters skipped, stops at the first "=", a dangling
    sixth bit group ignored."""
    kept = []
    for ch in text:
        if ch == "=":
            break
        if ch.isascii() and (ch.isalnum() or ch in "+/-_"):
            kept.append({"-": "+", "_": "/"}.get(ch, ch))
    body = "".join(kept)
    if len(body) % 4 == 1:
        body = body[:-1]
    return base64.b64decode(body + "=" * (-len(body) % 4))


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF


_P256_A = _P256_P - 3


_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B


_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296


_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def is_valid_p256_key(raw: bytes) -> bool:
    """SEC 1 §3.2.2 for an uncompressed point: 0x04 ‖ X ‖ Y, X and Y below p, on y² = x³ − 3x + b. The cofactor is 1."""
    if len(raw) != 65 or raw[0] != 0x04:
        return False
    x = int.from_bytes(raw[1:33], "big")
    y = int.from_bytes(raw[33:], "big")
    if x >= _P256_P or y >= _P256_P:
        return False
    return (y * y - (x * x * x + _P256_A * x + _P256_B)) % _P256_P == 0


def _jacobian_double(p: Tuple[int, int, int]) -> Tuple[int, int, int]:
    x, y, z = p
    if y == 0 or z == 0:
        return (0, 1, 0)
    ysq = y * y % _P256_P
    s = 4 * x * ysq % _P256_P
    zsq = z * z % _P256_P
    m = 3 * (x - zsq) * (x + zsq) % _P256_P  # a = −3
    nx = (m * m - 2 * s) % _P256_P
    ny = (m * (s - nx) - 8 * ysq * ysq) % _P256_P
    nz = 2 * y * z % _P256_P
    return (nx, ny, nz)


def _jacobian_add(p: Tuple[int, int, int], q: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1z1 = p[2] * p[2] % _P256_P
    z2z2 = q[2] * q[2] % _P256_P
    u1 = p[0] * z2z2 % _P256_P
    u2 = q[0] * z1z1 % _P256_P
    s1 = p[1] * q[2] * z2z2 % _P256_P
    s2 = q[1] * p[2] * z1z1 % _P256_P
    if u1 == u2:
        return _jacobian_double(p) if s1 == s2 else (0, 1, 0)
    h = (u2 - u1) % _P256_P
    r = (s2 - s1) % _P256_P
    hh = h * h % _P256_P
    hhh = h * hh % _P256_P
    v = u1 * hh % _P256_P
    nx = (r * r - hhh - 2 * v) % _P256_P
    ny = (r * (v - nx) - s1 * hhh) % _P256_P
    nz = h * p[2] * q[2] % _P256_P
    return (nx, ny, nz)


def _shamir(u1: int, u2: int, q: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """u1·G + u2·Q in affine form, or None at infinity."""
    g = (_P256_GX, _P256_GY, 1)
    qj = (q[0], q[1], 1)
    both = _jacobian_add(g, qj)
    out = (0, 1, 0)
    for bit in range(max(u1.bit_length(), u2.bit_length()) - 1, -1, -1):
        out = _jacobian_double(out)
        a, b = (u1 >> bit) & 1, (u2 >> bit) & 1
        if a and b:
            out = _jacobian_add(out, both)
        elif a:
            out = _jacobian_add(out, g)
        elif b:
            out = _jacobian_add(out, qj)
    if out[2] == 0:
        return None
    zinv = pow(out[2], -1, _P256_P)
    return (out[0] * zinv * zinv % _P256_P, out[1] * zinv * zinv * zinv % _P256_P)


def _der_integer(data: bytes, at: int) -> Tuple[Optional[int], int]:
    if at + 2 > len(data) or data[at] != 0x02:
        return None, at
    length = data[at + 1]
    start = at + 2
    if length == 0 or length > 33 or start + length > len(data):
        return None, at
    body = data[start:start + length]
    if body[0] & 0x80:
        return None, at  # negative
    if length > 1 and body[0] == 0 and not body[1] & 0x80:
        return None, at  # not minimal
    return int.from_bytes(body, "big"), start + length


def _der_signature(signature: bytes) -> Optional[Tuple[int, int]]:
    """An ASN.1 DER Ecdsa-Sig-Value (RFC 3279 §2.2.3), strictly: one SEQUENCE of two minimal positive INTEGERs."""
    if len(signature) < 8 or signature[0] != 0x30:
        return None
    if signature[1] & 0x80:
        return None  # a P-256 signature fits a short-form length
    if signature[1] != len(signature) - 2:
        return None
    r, at = _der_integer(signature, 2)
    if r is None:
        return None
    s, at = _der_integer(signature, at)
    if s is None or at != len(signature):
        return None
    return r, s


def es256_verify(x: bytes, y: bytes, message: bytes, signature: bytes) -> bool:
    """ECDSA P-256 with SHA-256 over `message`, the signature in DER (FIPS 186-5 §6.4.2). False, never an exception."""
    if not is_valid_p256_key(b"\x04" + x + y):
        return False
    parsed = _der_signature(signature)
    if parsed is None:
        return False
    r, s = parsed
    if not (1 <= r < _P256_N and 1 <= s < _P256_N):
        return False
    e = int.from_bytes(sha256(message), "big")
    w = pow(s, -1, _P256_N)
    point = _shamir(e * w % _P256_N, r * w % _P256_N, (int.from_bytes(x, "big"), int.from_bytes(y, "big")))
    return point is not None and point[0] % _P256_N == r


def b64url_decode(segment: str) -> bytes:
    """Base64url without padding, as Node reads it: a dangling sixth bit group is ignored."""
    if len(segment) % 4 == 1:
        segment = segment[:-1]
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
