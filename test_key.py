"""Smoke-test the OpenAI API key without printing secrets."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

from config import OPENAI_GENERATION_MODEL, PAPER_DIR


def _write_snapshot(status: str, detail: str) -> None:
    snapshot_dir = PAPER_DIR / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    (snapshot_dir / "api_smoke_test.txt").write_text(
        f"timestamp_utc={timestamp}\nstatus={status}\nmodel={OPENAI_GENERATION_MODEL}\n{detail}\n",
        encoding="utf-8",
    )


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        _write_snapshot("skipped", "reason=OPENAI_API_KEY is not set")
        raise SystemExit("OPENAI_API_KEY is not set in .env or the environment.")

    response = OpenAI().responses.create(
        model=OPENAI_GENERATION_MODEL,
        input="Reply with exactly: SMR API smoke test OK",
        max_output_tokens=16,
    )
    output = response.output_text.strip()
    _write_snapshot("ok", f"output={output}")
    print(f"API smoke test OK using {OPENAI_GENERATION_MODEL}: {output}")


if __name__ == "__main__":
    main()
