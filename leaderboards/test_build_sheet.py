from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path

from leaderboards import build_sheet as sheet


class SummarySheetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(Path(sheet.DEFAULT_DATA).read_text(encoding="utf-8"))
        cls.preview = json.loads(sheet.PREVIEW_RECORD.read_text(encoding="utf-8"))

    def test_retained_results_support_every_finding(self) -> None:
        self.assertEqual([], sheet.check_inputs(self.data, self.preview))

    def test_contradicted_finding_is_reported(self) -> None:
        data = deepcopy(self.data)
        for run in data["runs"]:
            if run["id"] == "20260821-nemotron35-nvfp4-dspark-n3":
                run["metrics"]["aggregate_output_tps"] = 1.0
        errors = sheet.check_inputs(data, self.preview)
        self.assertTrue(any(error.startswith("finding 1 no longer holds") for error in errors), errors)

    def test_missing_referenced_run_is_reported(self) -> None:
        data = deepcopy(self.data)
        data["runs"] = [run for run in data["runs"] if run["id"] != "20260821-exaone45-awq-mtp-n3"]
        errors = sheet.check_inputs(data, self.preview)
        self.assertTrue(any(error.startswith("finding 6: 20260821-exaone45-awq-mtp-n3") for error in errors), errors)

    def test_preview_throughput_comes_from_record_notes(self) -> None:
        self.assertAlmostEqual(113.351663, sheet.preview_c2_tps(self.preview))
        preview = deepcopy(self.preview)
        preview["notes"] = []
        self.assertIn("preview record notes no longer state the concurrency 2 throughput",
                      sheet.check_inputs(self.data, preview))

    def test_formulas_reference_only_generated_tabs(self) -> None:
        tabs = sheet.build_tabs(self.data, self.preview, "원본: test", suffix=sheet.STAGING)
        titles = {tab.title for tab in tabs.values()}
        references = {
            name
            for tab in tabs.values()
            for value in tab.cells.values()
            if isinstance(value, str) and value.startswith("=")
            for name in re.findall(r"'([^']+)'!", value)
        }
        self.assertTrue(references)
        self.assertLessEqual(references, titles)

    def test_request_batches_fit_one_gws_argument(self) -> None:
        tabs = sheet.build_tabs(self.data, self.preview, "원본: test")
        requests = sheet.content_requests(tabs, {key: index for index, key in enumerate(sheet.ORDER)})
        for batch in sheet.chunk(requests):
            body = json.dumps({"requests": batch}, ensure_ascii=False, separators=(",", ":"))
            self.assertLess(len(body.encode()), 128 * 1024)


if __name__ == "__main__":
    unittest.main()
