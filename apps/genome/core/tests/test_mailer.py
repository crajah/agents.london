"""Outbox sender — system-spec §10: durable rows, no-op without SMTP,
give-up after five failed attempts."""
import asyncio
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from genome_core import mailer


class Row:
    def __init__(self, pl):
        self.payload, self.id = pl, 1


class FC:
    def __init__(self, rows):
        self.rows, self.saved = rows, []

    async def find_vertices(self, *a, **k):
        return [Row(r) for r in self.rows]

    async def upsert_vertex(self, *a, **k):
        self.saved.append(k["payload"])


class TestMailer(unittest.TestCase):
    ROW = {"key": "m1", "to": "x@y.z", "subject": "s", "body": "b"}

    def test_noop_without_configuration(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            fc = FC([dict(self.ROW)])
            self.assertEqual(asyncio.run(mailer.send_pending(fc)), 0)
            self.assertEqual(fc.saved, [])     # rows wait, untouched

    def test_sends_and_marks(self):
        with mock.patch.dict("os.environ",
                             {"GENOME_SMTP_HOST": "smtp.test"}), \
             mock.patch.object(mailer, "_send_one") as send:
            fc = FC([dict(self.ROW)])
            self.assertEqual(asyncio.run(mailer.send_pending(fc)), 1)
            send.assert_called_once_with("x@y.z", "s", "b")
            self.assertIsNotNone(fc.saved[0]["sent_at"])

    def test_five_strikes_marks_failed(self):
        with mock.patch.dict("os.environ",
                             {"GENOME_SMTP_HOST": "smtp.test"}), \
             mock.patch.object(mailer, "_send_one",
                               side_effect=OSError("boom")):
            fc = FC([{**self.ROW, "attempts": 4}])
            self.assertEqual(asyncio.run(mailer.send_pending(fc)), 0)
            self.assertIsNotNone(fc.saved[0]["failed_at"])


if __name__ == "__main__":
    unittest.main()
