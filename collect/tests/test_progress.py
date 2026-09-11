import io
import unittest
from contextlib import redirect_stdout

from aimixe_collect.cli.render import ProgressBoard
from aimixe_collect.progress import Progress, human_bytes, human_rate, human_time, transfer_text


class ProgressTests(unittest.TestCase):
    def test_events_and_speed(self):
        events = []
        p = Progress(events.append, min_interval=0.0)
        p.step(record=1, records=3, stage="downloading")
        t = p.start("a", "file.pdf", 1000)
        t.started -= 2.0                      # pretend two seconds have passed
        p.update("a", 500, 1000)
        p.update("a", 1000, 1000)
        p.done("a", ok=True)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds, ["step", "start", "progress", "progress", "done"])
        prog = events[2]
        self.assertEqual(prog["percent"], 50.0)
        self.assertGreater(prog["speed"], 0)
        self.assertIsNotNone(prog["eta"])
        self.assertEqual(events[-1]["bytes"], 1000)
        self.assertEqual(events[-1]["counters"]["records"], 3)
        self.assertEqual(events[-1]["active"], [])

    def test_formatting(self):
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(3 * 1024 * 1024), "3.0 MB")
        self.assertEqual(human_rate(None), "—")
        self.assertEqual(human_time(75), "1m15s")
        text = transfer_text({"name": "a-very-long-file-name-that-goes-on-and-on.wav", "done": 2 * 1024 ** 2,
                              "total": 8 * 1024 ** 2, "percent": 25.0, "speed": 1024 ** 2, "eta": 6}, width=12)
        self.assertIn("25%", text)
        self.assertIn("eta 6s", text)
        self.assertTrue(text.startswith("a-very-long…"))

    def test_board_prints_completions_and_status(self):
        out = io.StringIO()
        with redirect_stdout(out):
            board = ProgressBoard(enabled=True)
            p = Progress(board.handle, min_interval=0.0)
            p.step(record=2, records=5, stage="downloading")
            p.start("x", "grammar.pdf", 100)
            p.update("x", 50, 100)
            board.print_line("  stored  100 grammar.pdf")
            p.done("x", ok=True)
            board.finish()
        text = out.getvalue()
        self.assertIn("record 2/5", text)
        self.assertIn("✓ grammar.pdf", text)
        self.assertIn("stored  100 grammar.pdf", text)
        self.assertIn("\r", text)                    # redrawn in place


if __name__ == "__main__":
    unittest.main()
