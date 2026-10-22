"""fabric_crypto's Ed25519 signing path (FAA-78, finding 45): the scalar multiplication that touches a secret (the
private scalar and the per-signature nonce) runs the same steps for every scalar, so how long it takes does not tell
the scalar's bits. Verification keeps the faster multiplication: everything it multiplies is public."""

import importlib
import random
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fc = importlib.import_module("fabric_crypto")
fp = importlib.import_module("fabric_package")

# RFC 8032 section 7.1, TEST 1 and TEST 2.
RFC8032 = (
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
)


class CountingAdd:
    """Counts the point additions a multiplication makes: the step a variable-time ladder skips on a zero bit."""

    def __init__(self):
        self.calls = 0
        self.real = fc._ed_add

    def __enter__(self):
        def counted(a, b):
            self.calls += 1
            return self.real(a, b)
        fc._ed_add = counted
        return self

    def __exit__(self, *exc):
        fc._ed_add = self.real


class SecretMultiplicationTests(unittest.TestCase):
    def test_the_ladder_answers_what_the_plain_multiplication_answers(self):
        rng = random.Random(45)
        scalars = [0, 1, 2, 8, fc._ED_L - 1, fc._ED_L, fc._ED_L + 1, 2 ** 254, 2 ** 255 - 1, 2 ** 256 - 1]
        scalars += [rng.getrandbits(256) for _ in range(40)]
        for scalar in scalars:
            with self.subTest(scalar=scalar):
                self.assertEqual(fc._ed_encode_point(fc.ed_mul_secret(scalar, fc._ED_G)),
                                 fc._ed_encode_point(fc._ed_mul(scalar, fc._ED_G)))

    def test_every_scalar_takes_the_same_steps(self):
        counts = set()
        for scalar in (1, 2 ** 254, 2 ** 255 - 1, (1 << 254) | 1, int("a5" * 32, 16)):
            with CountingAdd() as counter:
                fc.ed_mul_secret(scalar, fc._ED_G)
            counts.add(counter.calls)
        self.assertEqual(counts, {512}, "one addition and one doubling for each of 256 bits, whatever the bits are")

    def test_signing_takes_the_same_steps_for_any_key(self):
        """The signer's two secret multiplications (the public key from the scalar, R from the nonce) do not branch on
        either: two keys of very different Hamming weight make the same number of point additions."""
        counts = set()
        for seed in (bytes(32), b"\xff" * 32, bytes.fromhex(RFC8032[0][0])):
            with CountingAdd() as counter:
                fp.ed25519_sign(seed, b"the same message")
            counts.add(counter.calls)
        self.assertEqual(len(counts), 1, counts)

    def test_rfc_8032_vectors(self):
        for seed, public, message, signature in RFC8032:
            with self.subTest(public=public[:8]):
                self.assertEqual(fp.ed25519_public_key(bytes.fromhex(seed)).hex(), public)
                self.assertEqual(fp.ed25519_sign(bytes.fromhex(seed), bytes.fromhex(message)).hex(), signature)
                self.assertTrue(fc.ed25519_verify(bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)))


class DocstringTests(unittest.TestCase):
    def test_the_module_says_what_es256_verify_reads(self):
        self.assertNotIn("DER or raw", fc.__doc__)
        self.assertIn("DER", fc.es256_verify.__doc__)


if __name__ == "__main__":
    unittest.main()
