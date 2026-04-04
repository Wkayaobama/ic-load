from __future__ import annotations

from context.config import load_entity_translation_contract


def test_translation_contract_keeps_business_and_resolution_layers_separate():
    contract = load_entity_translation_contract()

    company = contract["company"]
    assert company["silver"]["canonical_fields"]["icalps_company_id"] == "comp_companyid"
    assert company["resolution"]["stacksync_record_id_column"] == "stacksync_record_id_9vpp8v"
    assert "stacksync_record_id_9vpp8v" not in company["silver"]["canonical_fields"].values()

    contact = contract["contact"]
    assert contact["gold"]["match_field"] == "icalps_contact_id"
    assert contact["gold"]["benchmark_export"].name.endswith("icalps_contact-2026-03-07.csv")

    opportunity = contract["opportunity"]
    assert "deal_stage_mapper.py" in opportunity["gold"]["business_rule"]

    communication = contract["communication"]
    assert communication["gold"]["target_boundary"] == "dbt marts -> hubspot.calls|notes|tasks|meetings"
    assert communication["resolution"]["association_resolution"]["company"]["stacksync_record_id_column"] == "stacksync_record_id_9vpp8v"
    assert communication["silver"]["canonical_fields"]["legacy_company_id"] == "company_id"
