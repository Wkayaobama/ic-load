from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from pipeline.dedupe import DedupeGuardrail


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the staging-vs-reference dedupe guardrail probe.")
    parser.add_argument("--entity", required=True, choices=["company", "contact", "opportunity", "communication", "case"])
    parser.add_argument("--candidate-csv")
    parser.add_argument("--reference-csv")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    guardrail = DedupeGuardrail()
    candidate = pd.read_csv(Path(args.candidate_csv), dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig") if args.candidate_csv else None
    reference = pd.read_csv(Path(args.reference_csv), dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig") if args.reference_csv else None
    result = guardrail.execute(args.entity, dry_run=True, candidate_frame=candidate, reference_frame=reference)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
