#!/usr/bin/env python3

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional validation dependency
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        if self.path != "/v1/chat/completions" or not payload.get("stream"):
            self.send_error(404)
            return
        chunks = [
            {"choices": [{"delta": {"content": "1 2"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": " 3 4"}, "finish_reason": "length"}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            },
        ]
        body = b"".join(
            f"data: {json.dumps(chunk)}\n\n".encode("utf-8") for chunk in chunks
        ) + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class CharacterizeIntegrationTest(unittest.TestCase):
    def test_preview_result_contract_and_privacy_boundary(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                output = Path(temporary_directory) / "result.json"
                completed = subprocess.run(
                    [
                        "python3",
                        str(ROOT / "characterize.py"),
                        "--base-url",
                        f"http://127.0.0.1:{server.server_port}/v1",
                        "--model",
                        "mock-model",
                        "--concurrency-points",
                        "1,2",
                        "--duration-s",
                        "0.05",
                        "--repetitions",
                        "1",
                        "--warmup-requests",
                        "1",
                        "--allow-nonstandard",
                        "--output",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertIn("Wrote", completed.stderr)
                result = json.loads(output.read_text(encoding="utf-8"))
                if jsonschema is not None:
                    schema = json.loads(
                        (ROOT / "characterization.schema.json").read_text(encoding="utf-8")
                    )
                    jsonschema.Draft202012Validator(schema).validate(result)
                self.assertEqual(result["classification"], "characterization-preview")
                self.assertFalse(result["compliance"]["compliant"])
                self.assertTrue(result["passed"])
                self.assertEqual([point["concurrency"] for point in result["curve"]], [1, 2])
                self.assertTrue(result["requests"])
                self.assertTrue(all(item["output_tokens"] == 4 for item in result["requests"]))
                serialized = json.dumps(result)
                self.assertNotIn("Write positive integers", serialized)
                self.assertNotIn('"prompt"', serialized)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
