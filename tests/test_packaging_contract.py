from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_repomix_bundle_includes_non_negotiable_algorithm_context():
    config = json.loads((ROOT / "GomplateRepoMix" / "repomix.config.json").read_text(encoding="utf-8"))
    include = set(config["include"])

    assert "../../unflatten_hierarchy.py" in include
    assert "../../ic_load_pipeline/python-ignorethis/custom_objects/upsert_sibling_companies.py" in include
    assert "../../custom_objects/SIBLING_COMPANY_PIPELINE.md" in include
    assert "../../ic_load_pipeline/python-ignorethis/deal_stage_mapper.py" in include
    assert "../../ic_load_pipeline/python-ignorethis/process_silver_layer.py" in include
    assert "../../ic_load_pipeline/python-ignorethis/process_opportunities.py" in include
    assert "../../DEAL_STAGE_MAPPING_VISUAL.md" in include
    assert "../../benchmark/benchmark_hubspot-crm-exports-icalps-companies-2026-03-07.csv" in include
    assert "../../benchmark/benchmark_hubspot-crm-exports-icalps_contact-2026-03-07.csv" in include
    assert "../../benchmark/benchmark_hubspot-crm-exports-icalps_deals-2026-03-07.csv" in include
    assert "../../benchmark/hubspot-crm-exports-all-tickets-2026-04-04-1.csv" in include
    assert "../docs/AD_HOC_TRANSFORM_CONTEXT.md" in include
    assert "../pipeline/text_normalization.py" in include
    assert "business_rules.yaml" in include
    assert "text_normalization_rules.yaml" in include
    assert "staging_metadata_snapshot.json" in include


def test_staging_metadata_snapshot_is_present_and_scoped_correctly():
    snapshot = json.loads((ROOT / "GomplateRepoMix" / "staging_metadata_snapshot.json").read_text(encoding="utf-8"))

    assert snapshot["scope"] == "staging_only"
    assert snapshot["rule"].startswith("Never read from or write to hubspot.*")
    assert snapshot["staging_tables"]["raw_stg_communication"]["row_count"] == 77100
    assert snapshot["staging_metrics"]["plural_domain_groups"] == 151
