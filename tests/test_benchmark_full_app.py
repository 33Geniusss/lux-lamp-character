from __future__ import annotations

from pathlib import Path
import unittest

from scripts.benchmark_full_app import build_application_command, summarize


class FullApplicationBenchmarkTests(unittest.TestCase):
    def test_missing_api_key_disables_llm_instead_of_prompting(self):
        command = build_application_command(
            Path("benchmark-python"),
            api_key_present=False,
        )

        self.assertEqual(command[-1], "--no-llm")
        self.assertIn("run.py", command[-2])

    def test_configured_api_key_keeps_llm_enabled(self):
        command = build_application_command(
            Path("benchmark-python"),
            api_key_present=True,
        )

        self.assertNotIn("--no-llm", command)
        self.assertIn("run.py", command[-1])

    def test_resource_samples_are_summarized(self):
        result = summarize(
            [
                {
                    "elapsed_s": 1.0,
                    "rss_mib": 100.0,
                    "cpu_cores": 0.5,
                    "process_count": 2.0,
                },
                {
                    "elapsed_s": 2.0,
                    "rss_mib": 120.0,
                    "cpu_cores": 1.0,
                    "process_count": 3.0,
                },
            ],
            steady_after=1.5,
        )

        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["peak_process_count"], 3)
        self.assertEqual(result["peak_rss_mib"], 120.0)
        self.assertEqual(result["steady_mean_cpu_cores"], 1.0)


if __name__ == "__main__":
    unittest.main()
