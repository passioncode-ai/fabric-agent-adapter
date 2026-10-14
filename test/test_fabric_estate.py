"""`estate-record/1` (contract DEC-0055) in the Python kit (FAA-31); the twin of fabric-estate.test.mjs.

Every answer here was given by the contract's own functions at the pin (test/fixtures/contract/estate-vectors.json,
made by make_estate_vectors.mjs): verifyEstateRecord's 49 cases (DEC-0063's signing RP and DEC-0066's skew among them), estateRecordRules over the contract's semantic
fixtures, the digest and challenge, P-256 keys and passkey keys. The last classes hold the delegation verifier to DL-14:
with an estate record, a token's kid is trusted only while a current revision certifies it (CT-20), and to DEC-0060's
`hubKeyCertified` (test/fixtures/contract/hub-key-vectors.json, vendor_vectors.mjs)."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest

from test_fabric_service import load

fe = load("fabric_estate")
dl = load("fabric_delegation")
HERE = Path(__file__).resolve().parent
V = json.loads((HERE / "fixtures/contract/estate-vectors.json").read_text(encoding="utf-8"))
DELEGATION = json.loads((HERE / "fixtures/delegation/vectors.json").read_text(encoding="utf-8"))
HUB = json.loads((HERE / "fixtures/contract/hub-key-vectors.json").read_text(encoding="utf-8"))


def der_of(r, s, pad_r=False, trailing=False, pad_s=False):
    """An Ecdsa-Sig-Value: SEQUENCE {INTEGER r, INTEGER s}, minimal unless asked otherwise."""
    def integer(n, pad=False):
        body = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
        if body[0] & 0x80:
            body = b"\x00" + body   # minimal: the one zero a positive integer with its top bit set needs
        if pad:
            body = b"\x00" + body   # one zero more than minimal
        return b"\x02" + bytes([len(body)]) + body
    inner = integer(r, pad_r) + integer(s, pad_s) + (b"\x00" if trailing else b"")
    return b"\x30" + bytes([len(inner)]) + inner


def clock(text):
    """The vectors' trust.at as the clock the port takes; a value no clock reads stays as it is (no-clock)."""
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return text


class ContractVectors(unittest.TestCase):
    def test_every_verify_case_answers_as_the_contract_does(self):
        self.assertEqual(len(V["verify"]), 49)
        problems = set()
        for case in V["verify"]:
            trust = case["trust"]
            kwargs = {"at": clock(trust.get("at"))}
            if "parent" in trust:
                kwargs["parent"] = trust["parent"]
            else:
                kwargs["authorities"] = trust.get("authorities")
            with self.subTest(case["name"]):
                got = fe.verify_estate_record(case["record"], **kwargs)
                self.assertEqual(got, case["expected"])
                problems.add(got.get("problem", "ok"))
        for expected in ("ok", "no-clock", "revoked-authority", "rule-violation", "bad-signature", "small-order-key", "broken-chain"):
            self.assertIn(expected, problems)

    def test_every_rule_case_answers_as_the_contract_does(self):
        for case in V["rules"]:
            with self.subTest(case["name"]):
                self.assertEqual(fe.estate_record_rules(case["kind"], case["value"]), case.get("expected"))
        codes = {f["code"] for c in V["rules"] for f in (c.get("expected") or [])}
        self.assertEqual(codes, {"FAC-SEM-072", "FAC-SEM-073", "FAC-SEM-074", "FAC-SEM-075", "FAC-SEM-076", "FAC-SEM-110", "FAC-SEM-111"})

    def test_a_grants_context_answers_as_the_contract_does(self):
        """FAC-SEM-110 (DEC-0082) on a grant of its own, against the contract's grant-context fixtures and variants."""
        self.assertGreaterEqual(len(V["grantContext"]), 7)
        for case in V["grantContext"]:
            with self.subTest(case["name"]):
                self.assertEqual(fe.grant_context_findings(case["value"], ""), case["expected"])

    def test_the_digest_the_challenge_and_placement_trust(self):
        for case in V["digests"]:
            self.assertEqual(fe.estate_record_digest(case["record"]), case["digest"])
            self.assertEqual(fe.estate_challenge_input(case["digest"]).decode("utf-8"), case["challengeInput"])
            self.assertEqual(fe.estate_challenge(case["digest"]).hex(), case["challenge"])
        for case in V["placementTrust"]:
            if "context" in case:  # DEC-0082: one placement per context
                self.assertEqual(fe.placement_trust(case["record"], case["machine"], case["agentRef"], case["context"]), case["expected"])
            else:
                self.assertEqual(fe.placement_trust(case["record"], case["machine"], case["agentRef"]), case["expected"])

    def test_p256_keys_and_passkey_keys(self):
        for case in V["p256"]:
            self.assertEqual(fe.is_valid_p256_key(bytes.fromhex(case["raw"])), case["expected"], case["name"])
        for case in V["credentialKeys"]:
            found = fe.credential_key(case["publicKey"], case["alg"])
            self.assertEqual({"problem": found["problem"]} if "problem" in found else {"ok": True}, case["expected"], case["name"])


class EcdsaAndTime(unittest.TestCase):
    """What the vectors reach only through whole records, checked on its own."""

    def test_es256_refuses_a_signature_that_is_not_strict_der(self):
        case = next(c for c in V["verify"] if c["expected"].get("ok") and c["record"]["signature"]["alg"] == "ES256")
        record = case["record"]
        sig = fe._b64url_bytes(record["signature"]["sig"])
        self.assertIsNotNone(fe._der_signature(sig))
        for broken in (sig + b"\x00", b"\x31" + sig[1:], sig[:1] + bytes([sig[1] + 1]) + sig[2:], b"\x30\x81" + bytes([len(sig) - 2]) + sig[2:]):
            self.assertIsNone(fe._der_signature(broken))
        r, s = fe._der_signature(sig)
        self.assertFalse(fe.es256_verify(b"\x00" * 32, b"\x00" * 32, b"x", sig), "an invalid key verifies nothing")
        padded = b"\x30" + bytes([sig[1] + 1]) + b"\x02" + bytes([sig[3] + 1]) + b"\x00" + sig[4:]
        self.assertIsNone(fe._der_signature(padded), "a non-minimal INTEGER is refused")
        self.assertTrue(r > 0 and s > 0)

    def test_es256_refuses_a_malleated_padded_or_trailing_signature_and_a_coordinate_beyond_p(self):
        case = next(c for c in V["verify"] if c["expected"].get("ok") and c["record"]["signature"]["alg"] == "ES256")
        record, authority = case["record"], next(a for a in case["trust"]["authorities"] if a["alg"] == "ES256")
        x, y = fe._b64url_bytes(authority["publicKey"]["x"]), fe._b64url_bytes(authority["publicKey"]["y"])
        signature = record["signature"]
        message = fe._b64url_bytes(signature["authenticatorData"]) + fe._sha256(fe._b64url_bytes(signature["clientDataJSON"]))
        der = fe._b64url_bytes(signature["sig"])
        self.assertTrue(fe.es256_verify(x, y, message, der))
        r, sv = fe._der_signature(der)
        # (r, n − s) is the same signature in low-S form, and its s has a clear top bit: one zero more than minimal stays
        # within 33 bytes, so only the minimality rule refuses it.
        low = fe._N - sv
        self.assertLess(low, 2 ** 255)
        self.assertTrue(fe.es256_verify(x, y, message, der_of(r, low)), "low-S is the same signature")
        padded = der_of(r, low, pad_s=True)
        for name, bad in (("s + n (malleated)", der_of(r, sv + fe._N)), ("a component padded with a zero", padded),
                          ("a byte inside the sequence after s", der_of(r, sv, trailing=True))):
            with self.subTest(name):
                self.assertFalse(fe.es256_verify(x, y, message, bad))
        # (p, √b) satisfies the curve equation only when x is read modulo p: x must be below p.
        root = pow(fe._B, (fe._P + 1) // 4, fe._P)
        self.assertEqual(root * root % fe._P, fe._B)
        self.assertFalse(fe.is_valid_p256_key(b"\x04" + fe._P.to_bytes(32, "big") + root.to_bytes(32, "big")))
        self.assertTrue(fe.is_valid_p256_key(b"\x04" + (0).to_bytes(32, "big") + root.to_bytes(32, "big")))

    def test_dates_are_strict_rfc_3339(self):
        self.assertEqual(fe.estate_time("2026-10-12T09:00:00Z"), 1791795600000.0)
        self.assertEqual(fe.estate_time("2026-10-12t09:00:00z"), 1791795600000.0)
        self.assertEqual(fe.estate_time("2026-10-12T11:00:00.123456+02:00"), 1791795600123.0)
        self.assertEqual(fe.estate_time("0000-01-01T00:00:00Z"), -62167219200000.0)
        for bad in ("2026-02-30T00:00:00Z", "2026-10-12 09:00:00Z", "2026-10-12T09:00:60Z", "2026-10-12T09:00:00", 1791795600, None):
            self.assertNotEqual(fe.estate_time(bad), fe.estate_time(bad), bad)  # NaN

    def test_the_clock_is_an_aware_datetime_or_epoch_seconds(self):
        case = next(c for c in V["verify"] if c["expected"].get("ok"))
        trust = case["trust"]
        aware = clock(trust["at"])
        kwargs = {"parent": trust["parent"]} if "parent" in trust else {"authorities": trust["authorities"]}
        self.assertTrue(fe.verify_estate_record(case["record"], at=aware.timestamp(), **kwargs)["ok"])
        self.assertEqual(fe.verify_estate_record(case["record"], at=aware.replace(tzinfo=None), **kwargs), {"ok": False, "problem": "no-clock"})


class NeverAnException(unittest.TestCase):
    """What JSON cannot carry into a vector: a verdict, never a crash, where the contract answers one."""

    def setUp(self):
        self.case = next(c for c in V["verify"] if c["expected"].get("ok") and "authorities" in c["trust"])
        self.trust = {"at": clock(self.case["trust"]["at"]), "authorities": self.case["trust"]["authorities"]}

    def test_a_revision_beyond_a_double_is_malformed(self):
        record = copy.deepcopy(self.case["record"])
        record["revision"] = 10 ** 400
        self.assertEqual(fe.verify_estate_record(record, **self.trust), {"ok": False, "problem": "malformed"})
        self.assertEqual(fe.verify_estate_record(self.case["record"], at=10 ** 400, authorities=self.trust["authorities"]),
                         {"ok": False, "problem": "no-clock"})

    def test_deeply_nested_client_data_is_malformed(self):
        signature = dict(self.case["record"]["signature"], clientDataJSON=fe._b64url(b"[" * 50000))
        credential = dict(self.trust["authorities"][0])
        credential = {k: credential[k] for k in ("credentialId", "alg", "publicKey", "rpId", "origins")}
        self.assertEqual(fe.verify_assertion(signature, credential, b"\x00" * 32), {"ok": False, "problem": "malformed"})

    def test_a_lone_surrogate_in_a_pinned_rp_id_is_the_wrong_rp(self):
        authorities = [dict(a, rpId="sign.example.org\ud800") for a in self.trust["authorities"]]
        self.assertEqual(fe.verify_estate_record(self.case["record"], at=self.trust["at"], authorities=authorities),
                         {"ok": False, "problem": "wrong-rp"})


class HubKeyCertified(unittest.TestCase):
    """DL-14 with DEC-0055 (contract CT-20): a delegation verifier that reads the estate record trusts a kid only while a
    current revision certifies it for a machine and does not revoke it."""

    def setUp(self):
        case = next(c for c in DELEGATION["delegation"] if c["expected"].get("ok"))
        self.token, self.options = case["token"], case["options"]
        self.kid = case["expected"]["kid"]
        self.jwks = self.options.get("jwks") or DELEGATION["jwks"]
        self.x = next(k["x"] for k in self.jwks["keys"] if k.get("kid") == self.kid)
        now = self.options["now"]
        iso = lambda seconds: dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.record = copy.deepcopy(V["digests"][0]["record"])
        self.record["issuedAt"], self.record["validUntil"] = iso(now - 3600), iso(now + 3600)
        self.record["machines"][0]["hubKey"] = {**self.record["machines"][0]["hubKey"], "kid": self.kid, "x": self.x}
        self.now = now

    def verify(self, estate):
        o = self.options
        return dl.verify_delegation(self.token, audience=o["audience"], jwks=self.jwks, now=o["now"], capability=o["capability"],
                                    effect=o["effect"], issuer=o["issuer"], read_only=o.get("readOnly", False), estate=estate)

    def test_a_certified_kid_is_trusted_and_no_record_changes_nothing(self):
        self.assertEqual(fe.hub_key_certified(self.record, self.kid, self.x, self.now),
                         {"certified": True, "machine": self.record["machines"][0]["id"], "revision": self.record["revision"]})
        self.assertTrue(self.verify(None)["ok"])
        self.assertTrue(self.verify(self.record)["ok"])
        self.assertTrue(self.verify(lambda: self.record)["ok"], "a callable gives the current revision")

    def test_an_uncertified_revoked_or_stale_kid_is_refused(self):
        other = copy.deepcopy(self.record)
        other["machines"][0]["hubKey"]["kid"] = "another-kid"
        moved = copy.deepcopy(self.record)
        moved["machines"][0]["hubKey"]["x"] = "B" * 43
        revoked = copy.deepcopy(self.record)
        revoked["revocations"] = list(revoked.get("revocations") or []) + [{"kind": "hub-key", "ref": self.kid}]
        for name, record in (("another kid", other), ("another key under the kid", moved), ("revoked", revoked)):
            with self.subTest(name):
                verdict = self.verify(record)
                self.assertEqual((verdict["ok"], verdict.get("code"), verdict.get("detail")), (False, "unauthenticated", "kid-not-certified"))
        # DEC-0060: a revision whose window cannot hold the clock is the trust source's fault, not the token's.
        stale = copy.deepcopy(self.record)
        stale["validUntil"] = stale["issuedAt"]
        verdict = self.verify(stale)
        self.assertEqual((verdict["ok"], verdict.get("code"), verdict.get("detail")), (False, "issuer-unavailable", "estate-unreadable"))

    def test_an_unreadable_record_certifies_nothing(self):
        def broken():
            raise OSError("the record store is down")
        verdict = self.verify(broken)
        self.assertEqual((verdict["ok"], verdict.get("code"), verdict.get("detail")), (False, "issuer-unavailable", "estate-unreadable"))

    def test_approvals_and_the_gate_follow_the_record(self):
        step = next(st for c in DELEGATION["approvals"] for st in c["steps"] if st["expected"].get("ok"))
        o = step["options"]
        jwks = o.get("jwks") or DELEGATION["jwks"]
        kid = step["expected"]["kid"]
        record = copy.deepcopy(self.record)
        record["machines"][0]["hubKey"] = {**record["machines"][0]["hubKey"], "kid": kid, "x": next(k["x"] for k in jwks["keys"] if k.get("kid") == kid)}
        iso = lambda seconds: dt.datetime.fromtimestamp(seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record["issuedAt"], record["validUntil"] = iso(o["now"] - 60), iso(o["now"] + 60)

        def approve(estate):
            return dl.verify_approval(step["approval"], audience=o["audience"], jwks=jwks, now=o["now"], action_digest=o["actionDigest"],
                                      jti_store=dl.MemoryJtiStore(), issuer=o["issuer"], estate=estate)
        self.assertTrue(approve(record)["ok"])
        record["machines"][0]["hubKey"]["kid"] = "another-kid"
        self.assertEqual(approve(record).get("detail"), "kid-not-certified")
        self.assertEqual(approve(record).get("code"), "approval-invalid")

        o = self.options
        gate = dl.delegation_gate(audience=o["audience"], jwks=self.jwks, effects={o["capability"]: o["effect"]},
                                  issuer=o["issuer"], clock=lambda: self.now, estate=lambda: {})
        refused = gate(o["capability"], {"Fabric-Delegation": self.token})
        self.assertEqual((refused.get("code"), refused.get("detail")), ("issuer-unavailable", "estate-unreadable"))
        gate = dl.delegation_gate(audience=o["audience"], jwks=self.jwks, effects={o["capability"]: o["effect"]},
                                  issuer=o["issuer"], clock=lambda: self.now, estate=lambda: self.record,
                                  estate_applied={"revision": self.record["revision"] + 1})
        refused = gate(o["capability"], {"Fabric-Delegation": self.token})
        self.assertEqual((refused.get("code"), refused.get("detail")), ("issuer-unavailable", "estate-rolled-back"))


class HubKeyVectors(unittest.TestCase):
    """DEC-0060: `hubKeyCertified` and the verifiers' row 4a, held to the contract's own answers."""

    def test_every_hub_key_case_answers_as_the_contract_does(self):
        self.assertEqual(len(HUB["cases"]), 51)
        details = set()
        for case in HUB["cases"]:
            extra = case["extraRevocations"] if "extraRevocations" in case else fe._MISSING
            with self.subTest(case["name"]):
                got = fe.hub_key_certified(case["record"], case["kid"], case.get("x", fe._MISSING), case["at"], case.get("applied"), extra)
                self.assertEqual(got, case["expected"])
                details.add(got.get("detail", "certified"))
        self.assertEqual(details, {"certified", "kid-not-certified", "estate-unreadable", "estate-outside-window",
                                   "estate-rolled-back", "estate-forked", "no-clock"})

    def test_every_verifier_answer_matches(self):
        self.assertEqual(len(HUB["verifier"]), 14)
        for case in HUB["verifier"]:
            kwargs = {"audience": "example-media", "jwks": HUB["jwks"], "now": case["now"], "issuer": HUB["issuer"]}
            if "estate" in case:
                source = case["estate"]
                if source.get("throws"):
                    def broken():
                        raise OSError("the record store is down")
                    kwargs["estate"] = broken
                elif source["record"] is None:
                    kwargs["estate"] = lambda: None   # a null source, as the vectors' `about` says a port without undefined passes it
                else:
                    kwargs["estate"] = source["record"]
            if "estateApplied" in case:
                kwargs["estate_applied"] = case["estateApplied"]
            with self.subTest(case["name"]):
                if case["document"] == "approval":
                    got = dl.verify_approval(case["token"], action_digest=HUB["actionDigest"], jti_store=dl.MemoryJtiStore(), **kwargs)
                else:
                    got = dl.verify_delegation(case["token"], capability="media.render", effect="draft", **kwargs)
                want = case["expected"]
                self.assertEqual(got["ok"], want["ok"])
                if not want["ok"]:
                    self.assertEqual((got["code"], got["detail"]), (want["code"], want["detail"]))

    def test_a_revocation_ref_is_compared_exactly(self):
        """DEC-0060 (i): a ref is compared as it is, never after a string conversion."""
        case = HUB["cases"][0]
        record = copy.deepcopy(case["record"])
        record["machines"][0]["id"] = 7
        record["revocations"] = [{"kind": "machine", "ref": "7", "revokedAt": "2026-10-21T09:00:00Z"}]
        self.assertTrue(fe.hub_key_certified(record, case["kid"], case["x"], case["at"])["certified"])
        record["revocations"][0]["ref"] = 7
        self.assertEqual(fe.hub_key_certified(record, case["kid"], case["x"], case["at"])["detail"], "kid-not-certified")

    def test_an_unreadable_clock_is_refused_first(self):
        o = HUB["verifier"][0]
        for now in (float("nan"), float("inf"), "1792918830", True, 8.64e12 + 1, None):
            with self.subTest(now=now):
                got = dl.verify_delegation(o["token"], audience="example-media", jwks=HUB["jwks"], now=now, capability="media.render",
                                           effect="draft", issuer=None)
                self.assertEqual((got["code"], got["detail"]), ("unknown-state", "no-clock"))
        got = dl.verify_approval("x.y.z", audience="example-media", jwks=HUB["jwks"], now=float("nan"), action_digest=HUB["actionDigest"],
                                 jti_store=dl.MemoryJtiStore(), issuer=HUB["issuer"])
        self.assertEqual((got["code"], got["detail"]), ("unknown-state", "no-clock"))

    def test_the_delta_revocations_pass_through_the_verifier(self):
        case = HUB["verifier"][0]
        record = case["estate"]["record"]
        for extra in ([{"kind": "hub-key", "ref": "hub-m-4c1e-1", "revokedAt": "2026-10-21T09:00:00Z"}],
                      lambda: [{"kind": "machine", "ref": "m-4c1e", "revokedAt": "2026-10-21T09:00:00Z"}]):
            got = dl.verify_delegation(case["token"], audience="example-media", jwks=HUB["jwks"], now=case["now"], capability="media.render",
                                       effect="draft", issuer=HUB["issuer"], estate=record, estate_revocations=extra)
            self.assertEqual((got["code"], got["detail"]), ("unauthenticated", "kid-not-certified"))


class SigningRp(unittest.TestCase):
    """DEC-0063: the estate passkey is a signing credential (FAC-SEM-092)."""

    def test_signing_rp_ids_and_origins(self):
        for rp, ok in (("sign.example.org", True), ("sign.a.b.c", True), ("sign.org", False), ("example.org", False),
                       ("SIGN.example.org", False), ("sign.example.org.", False), (None, False), ("sign." + "a" * 63 + ".org", True), ("sign." + "a" * 64 + ".org", False)):
            with self.subTest(rp=rp):
                self.assertEqual(fe.is_signing_rp_id(rp), ok)
        for origin, ok in (("https://sign.example.org", True), ("https://x.sign.example.org", True), ("https://sign.example.org:443", False),
                           ("http://sign.example.org", False), ("https://evilsign.example.org", False), ("https://sign.example.org/", False)):
            with self.subTest(origin=origin):
                self.assertEqual(fe.origin_within(origin, "sign.example.org"), ok)

    def test_the_record_rules_flag_a_sign_in_credential(self):
        record = copy.deepcopy(V["digests"][0]["record"])
        record["authorities"][0]["rpId"] = "example.org"
        codes = [f for f in fe._record_findings(record) if f["code"] == "FAC-SEM-092"]
        self.assertEqual([f["instancePath"] for f in codes], ["/authorities/0/rpId"])
        record["authorities"][0]["rpId"] = "sign.example.org"
        record["authorities"][0]["origins"] = ["https://sign.example.org", "https://example.org"]
        codes = [f for f in fe._record_findings(record) if f["code"] == "FAC-SEM-092"]
        self.assertEqual([f["instancePath"] for f in codes], ["/authorities/0/origins/1"])


if __name__ == "__main__":
    unittest.main()
