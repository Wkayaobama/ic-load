from __future__ import annotations

from context.config import load_entity_translation_contract


def test_translation_contract_keeps_business_and_resolution_layers_separate():
    contract = load_entity_translation_contract()

    company = contract["company"]
    assert company["silver"]["canonical_fields"]["icalps_company_id"] == "icalps_company_id"
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


def test_pillar_b_column_naming_alignment():
    """Silver normalised_primary_key and canonical_fields reflect HubSpot property names post-Pillar B rename."""
    contract = load_entity_translation_contract()

    # Primary keys use HubSpot internal names
    assert contract["company"]["silver"]["normalised_primary_key"] == "icalps_company_id"
    assert contract["contact"]["silver"]["normalised_primary_key"] == "icalps_contact_id"
    assert contract["opportunity"]["silver"]["normalised_primary_key"] == "icalps_deal_id"

    # Opportunity: certainty maps to icalps_oppocertainty, not the old icalps_dealcertainty
    oppo_fields = contract["opportunity"]["silver"]["canonical_fields"]
    assert "icalps_oppocertainty" in oppo_fields
    assert "icalps_dealcertainty" not in oppo_fields

    # Opportunity: computed HubSpot Calculation fields must not be in the contract
    assert "icalps_netamount_k__" not in oppo_fields
    assert "icalps_net_weighted_amount" not in oppo_fields

    # Opportunity: close date uses internal HubSpot property name
    assert "icalps_closedate" in oppo_fields

    # Contact: renamed fields present under new names
    contact_fields = contract["contact"]["silver"]["canonical_fields"]
    assert "icalps_perstitle" in contact_fields.values()
    assert "icalps_contactstatus" not in contact_fields.values()  # not in contract (internal only)
    assert "firstname" in contact_fields.values()
    assert "pers_firstname" not in contact_fields.values()

    # Company: sector uses the canonical ontologie name
    company_fields = contract["company"]["silver"]["canonical_fields"]
    assert "icalps_industry_drill_down" in company_fields.values()
    assert "comp_sector" not in company_fields.values()
