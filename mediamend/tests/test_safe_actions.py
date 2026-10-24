import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import safe_actions as sa


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.root = Path(self.d.name)
        self.f = self.root / "a.txt"; self.f.write_text("hello")

    def tearDown(self): self.d.cleanup()

    def test_roundtrip_preserves_hash(self):
        h = sa.sha256(self.f); e = sa.move_to_bin(self.root, self.f)
        self.assertFalse(self.f.exists())
        sa.restore(self.root, e["id"])
        self.assertEqual(sa.sha256(self.f), h)

    def test_restore_never_overwrites(self):
        e = sa.move_to_bin(self.root, self.f); self.f.write_text("new")
        with self.assertRaises(sa.ActionError): sa.restore(self.root, e["id"])
        self.assertEqual(self.f.read_text(), "new")

    def test_archive_then_cannot_delete(self):
        e = sa.move_to_bin(self.root, self.f); sa.archive(self.root, e["id"])
        with self.assertRaises(sa.ActionError): sa.delete_permanent(self.root, e["id"])

    def test_delete_only_from_bin(self):
        e = sa.move_to_bin(self.root, self.f); sa.delete_permanent(self.root, e["id"])
        self.assertFalse(Path(e["current_path"]).exists())

    def test_rejects_outside_root(self):
        with tempfile.TemporaryDirectory() as o:
            x = Path(o) / "x.txt"; x.write_text("x")
            with self.assertRaises(sa.ActionError): sa.move_to_bin(self.root, x)

    def test_zero_byte(self):
        z = self.root / "z.wav"; z.touch()
        e = sa.move_to_bin(self.root, z); sa.restore(self.root, e["id"]); self.assertTrue(z.exists())


if __name__ == "__main__":
    unittest.main()
