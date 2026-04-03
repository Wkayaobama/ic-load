from __future__ import annotations

from pathlib import Path

from sql.render import (
    render_association_bridge,
    render_engagement_upsert,
    render_entity_upsert,
    write_all_rendered_sql,
)


def test_entity_upsert_render_contains_on_conflict():
    sql_text = render_entity_upsert("Company")
    assert "ON CONFLICT" in sql_text
    assert "hubspot.companies" in sql_text
    assert "Bronze_Company" in sql_text


def test_engagement_upsert_render_contains_not_exists():
    sql_text = render_engagement_upsert("Calls")
    assert "NOT EXISTS" in sql_text
    assert "unique_id" in sql_text
    assert "hubspot.calls" in sql_text


def test_association_render_is_two_pass_and_idempotent():
    sql_text = render_association_bridge("Calls", "company")
    assert "Pass A: StackSync UUID" in sql_text
    assert "Pass B: legacy ID fallback" in sql_text
    assert "UNION" in sql_text
    assert "NOT EXISTS" in sql_text
    assert "association_type_id" in sql_text


def test_rendered_sql_is_stable_for_same_inputs():
    first = render_association_bridge("Notes", "deal")
    second = render_association_bridge("Notes", "deal")
    assert first == second


def test_write_all_rendered_sql_outputs_expected_files():
    tmp_path = Path.cwd() / "sql" / "rendered" / "test_output"
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = write_all_rendered_sql(output_dir=tmp_path)
    assert len(paths) == 14
    assert (tmp_path / "upsert_company.sql").exists()
    assert (tmp_path / "engagement_calls.sql").exists()
    assert (tmp_path / "association_notes_deal.sql").exists()
