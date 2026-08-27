#!/usr/bin/env python3
"""Verify a persisted smoke run and its artifact content."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from mlflow import MlflowClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    args = parser.parse_args()

    client = MlflowClient(tracking_uri=args.tracking_uri)
    run = client.get_run(args.run_id)
    with tempfile.TemporaryDirectory(prefix="mlflow-smoke-") as directory:
        downloaded = Path(
            client.download_artifacts(
                args.run_id,
                "validation/smoke.json",
                directory,
            )
        )
        payload = json.loads(downloaded.read_text(encoding="utf-8"))

    if run.info.status != "FINISHED" or payload.get("status") != "ok":
        raise RuntimeError(
            f"invalid persisted smoke run: run={run.info.status}, artifact={payload}"
        )

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": args.run_id,
                "run_status": run.info.status,
                "artifact_status": payload["status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
