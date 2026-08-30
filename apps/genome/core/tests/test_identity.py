"""genome-spec §6: the chain, the counter, the refusals. Skips cleanly where
`cryptography` is absent (stdlib-only runners); the venv and images carry it."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from genome_core import identity as I


@unittest.skipUnless(I.HAVE_CRYPTO, "cryptography not installed")
class TestIdentityChain(unittest.TestCase):
    def setUp(self):
        self.root = I.make_root()
        self.rp = self.root["doc"]["public_pem"].encode()
        self.w1 = I.issue_world_cert(self.root, "world-1")
        self.ident = I.identity_hash({"Aggression": 5000}, "world-1", "agent-9")
        self.ac = I.issue_agent_cert(self.w1, "agent-9", self.ident)

    def test_chain_verifies(self):
        self.assertTrue(I.verify_chain(self.rp, self.w1, self.ac))

    def test_identity_hash_stable_under_key_order(self):
        a = I.identity_hash({"A": 1, "B": 2}, "w", "a")
        b = I.identity_hash({"B": 2, "A": 1}, "w", "a")
        self.assertEqual(a, b)                      # Rule 6.7 canonical

    def test_transfer_accept_then_replay_refused(self):
        t = I.make_transfer(self.w1, self.ac, 1, "world-2")
        ok, _ = I.accept_transfer(self.rp, self.w1, self.ac, t, 0)
        self.assertTrue(ok)
        ok, why = I.accept_transfer(self.rp, self.w1, self.ac, t, 1)
        self.assertFalse(ok); self.assertIn("replay", why)   # Rules 6.11/6.12

    def test_tampered_assertion_refused(self):
        t = I.make_transfer(self.w1, self.ac, 2, "world-2")
        t2 = {**t, "doc": {**t["doc"], "to_world": "world-EVIL"}}
        ok, why = I.accept_transfer(self.rp, self.w1, self.ac, t2, 1)
        self.assertFalse(ok)

    def test_forged_world_cert_refused(self):
        fake_root = {"private_pem": I.Keypair.generate().private_pem.decode(),
                     "doc": {}}
        w_evil = I.issue_world_cert(fake_root, "world-1")
        self.assertFalse(I.verify_chain(self.rp, w_evil, self.ac))


if __name__ == "__main__":
    unittest.main(verbosity=1)
