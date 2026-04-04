from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.text_normalization import clean_text_fields, clean_text_utf8


ROOT = Path(__file__).resolve().parent.parent


def test_text_normalization_rules_are_packaged_as_universal_contract():
    rules = yaml.safe_load((ROOT / "GomplateRepoMix" / "text_normalization_rules.yaml").read_text(encoding="utf-8"))

    assert rules["scope"] == "universal_across_entities"
    assert rules["non_negotiable"] is True
    assert "case" in rules["applies_to"]
    assert rules["read_contract"]["csv_encoding"] == "utf-8-sig"


def test_clean_text_utf8_repairs_common_mojibake_and_preserves_semantic_lines():
    raw = "  A l'Ã©tape post Tape-out:\r\n\r\n- RÃ©ponse clientâ€™s test \x00  "
    cleaned = clean_text_utf8(raw)

    assert cleaned == "A l'étape post Tape-out:\n\n- Réponse client's test"


def test_clean_text_fields_only_mutates_selected_fields():
    record = {
        "description": "Questionnaire client Ã©tape \r\n",
        "priority": "Normal",
    }

    cleaned = clean_text_fields(record, ["description"])

    assert cleaned["description"] == "Questionnaire client étape"
    assert cleaned["priority"] == "Normal"
