// The Node kit's cryptography helpers, once (FAA-65, layer L1); the twin of fabric_crypto.py. Signature verification
// itself is Node's (`crypto.verify`); what lives here is what the runtime does not refuse on its own: keys of small
// order (DEC-0045) and P-256 points off the curve, plus sha256. Node 20+, no dependency.
import crypto from 'node:crypto';

export const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest();

// The small-order points of edwards25519 and their non-canonical encodings, compared with the sign bit cleared
// (libsodium's has_small_order list). Under such a key, R = [S]B verifies for a quarter or more of all messages, and
// Node before 26 lets OpenSSL accept it: the kit refuses these keys itself rather than trust the runtime.
export const SMALL_ORDER_ENCODINGS = Object.freeze([
  '0000000000000000000000000000000000000000000000000000000000000000', '0100000000000000000000000000000000000000000000000000000000000000',
  '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05', 'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a',
  'ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f', 'edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
  'eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
]);
const cleared = (raw) => { const copy = Buffer.from(raw); copy[31] &= 0x7f; return copy.toString('hex'); };

/** Whether a 32-byte Ed25519 public key is a point of small order (in any encoding); a key of another length is not one. */
export function isSmallOrderKey(key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) return false;
  return SMALL_ORDER_ENCODINGS.includes(cleared(key));
}

/** The contract's isSmallOrderKey as the estate record reads a hub key: a key that is not 32 bytes counts as one too. */
export const isSmallOrderOrMalformed = (raw) => raw.length !== 32 || SMALL_ORDER_ENCODINGS.includes(cleared(raw));

const P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const P256_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604bn;
const toBig = (part) => BigInt(`0x${Buffer.from(part).toString('hex')}`);

/** Whether `raw` is a valid uncompressed P-256 public key: 0x04 ‖ X ‖ Y, both below p, on the curve. */
export function isValidP256Key(raw) {
  if (raw.length !== 65 || raw[0] !== 0x04) return false;
  const x = toBig(raw.subarray(1, 33));
  const y = toBig(raw.subarray(33, 65));
  if (x >= P256_P || y >= P256_P) return false;
  const left = (y * y) % P256_P;
  const right = (((x * x) % P256_P) * x - 3n * x + P256_B) % P256_P;
  return left === ((right % P256_P) + P256_P) % P256_P;
}
