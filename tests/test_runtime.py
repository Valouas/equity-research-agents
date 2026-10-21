import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stockbot.cli import load_env, next_run, valid_symbols


class RuntimeTests(unittest.TestCase):
    def test_schedule_keeps_swiss_local_time_across_winter_change(self):
        zone = ZoneInfo("Europe/Zurich")
        now = datetime(2026, 10, 24, 23, 30, tzinfo=zone)
        target = next_run(now, "23:15")
        self.assertEqual(target.isoformat(), "2026-10-25T23:15:00+01:00")

    def test_env_file_is_data_and_existing_env_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / ".env"
            file.write_text("EODHD_API_TOKEN=from_file\nUNKNOWN=$(do_not_execute)\n", encoding="utf-8")
            with patch.dict("os.environ", {"EODHD_API_TOKEN": "from_environment"}, clear=True):
                import os
                load_env(file)
                self.assertEqual(os.environ["EODHD_API_TOKEN"], "from_environment")
                self.assertNotIn("UNKNOWN", os.environ)

    def test_symbols_cannot_be_urls_or_inject_query_parameters(self):
        self.assertEqual(valid_symbols("aapl.us,AMZN.US,aapl.us"), ["AAPL.US", "AMZN.US"])
        with self.assertRaises(ValueError):
            valid_symbols("https://example.test/?api_token=secret")


if __name__ == "__main__":
    unittest.main()
