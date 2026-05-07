from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from pipeline.dedupe import DedupeGuardrail


def _make_output_dir(name: str):
    path = Path.cwd() / "artifacts" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_decisions(output_dir, entity: str) -> pd.DataFrame:
    return pd.read_csv(output_dir / f"dedupe_{entity}.csv")


def test_company_exact_canonical_id_is_safe():
    output_dir = _make_output_dir("test_dedupe_company_safe")
    guardrail = DedupeGuardrail(output_dir=output_dir)
    candidate = pd.DataFrame(
        [
            {
                "comp_companyid": "1001",
                "comp_name": "Acme Solutions SAS",
                "comp_website": "https://www.acme.com",
                "address_city": "Grenoble",
                "icalps_companyphone": "+33 4 76 00 00 00",
            }
        ]
    )
    reference = pd.DataFrame(
        [
            {
                "icalps_company_id": "1001",
                "Company name": "Acme Solutions",
                "Company Domain Name": "acme.com",
                "City": "Grenoble",
                "Icalps_CompanyPhone": "+33 4 76 00 00 00",
            }
        ]
    )

    result = guardrail.execute("company", dry_run=True, candidate_frame=candidate, reference_frame=reference)

    assert result["safe_count"] == 1
    decisions = _read_decisions(output_dir, "company")
    assert decisions.loc[0, "decision"] == "safe"
    assert decisions.loc[0, "reason"] == "exact_canonical_id_match"


def test_company_same_domain_and_name_blocks_duplicate():
    output_dir = _make_output_dir("test_dedupe_company_block")
    guardrail = DedupeGuardrail(output_dir=output_dir)
    candidate = pd.DataFrame(
        [
            {
                "comp_companyid": "2001",
                "comp_name": "Acme Microsystems GmbH",
                "comp_website": "https://acme-micro.com",
                "address_city": "Zurich",
                "icalps_companyphone": "+41 44 555 0000",
            }
        ]
    )
    reference = pd.DataFrame(
        [
            {
                "icalps_company_id": "9999",
                "Company name": "Acme Microsystems",
                "Company Domain Name": "acme-micro.com",
                "City": "Zurich",
                "Icalps_CompanyPhone": "+41 44 555 0000",
            }
        ]
    )

    result = guardrail.execute("company", dry_run=True, candidate_frame=candidate, reference_frame=reference)

    assert result["block_count"] == 1
    decisions = _read_decisions(output_dir, "company")
    assert decisions.loc[0, "decision"] == "block"
    assert float(decisions.loc[0, "score"]) >= 0.82


def test_contact_exact_email_blocks_duplicate():
    output_dir = _make_output_dir("test_dedupe_contact_block")
    guardrail = DedupeGuardrail(output_dir=output_dir)
    candidate = pd.DataFrame(
        [
            {
                "pers_personid": "200",
                "pers_companyid": "300",
                "pers_firstname": "Ada",
                "pers_lastname": "Lovelace",
                "icalps_email": "ada@example.com",
                "icalps_businessphone": "+33 1 02 03 04 05",
                "icalps_mobilephone": None,
            }
        ]
    )
    reference = pd.DataFrame(
        [
            {
                "icalps_contact_id": "999",
                "Email": "ada@example.com",
                "First Name": "Ada",
                "Last Name": "Lovelace",
                "Primary Associated Company ID": "300",
                "Phone Number": "+33 1 02 03 04 05",
                "IcAlps_BusinessPhone": "",
            }
        ]
    )

    result = guardrail.execute("contact", dry_run=True, candidate_frame=candidate, reference_frame=reference)

    assert result["block_count"] == 1
    decisions = _read_decisions(output_dir, "contact")
    assert decisions.loc[0, "decision"] == "block"
    assert "email_exact" in decisions.loc[0, "reason"]


def test_case_similarity_can_land_in_review_band():
    output_dir = _make_output_dir("test_dedupe_case_review")
    guardrail = DedupeGuardrail(output_dir=output_dir)
    candidate = pd.DataFrame(
        [
            {
                "icalps_ticket_id": "501",
                "subject": "Questionnaire satisfaction retour",
                "icalps_company_id": "1119",
                "icalps_contact_email": "",
                "icalps_case_status": "Open",
                "icalps_case_stage": "Confirmed",
                "hs_ticket_priority": "MEDIUM",
            }
        ]
    )
    reference = pd.DataFrame(
        [
            {
                "IcAlps_TicketID": "777",
                "Ticket name": "Retour questionnaire satisfaction",
                "IcAlps_CompanyID": "1119",
                "IcAlps_TicketPersonEmailAddress": "nicolas.quesne@vitec.com",
                "Ticket status": "Closed",
                "IcAlps_TicketStage": "Confirmed",
                "Priority": "Medium",
            }
        ]
    )

    result = guardrail.execute("case", dry_run=True, candidate_frame=candidate, reference_frame=reference)

    assert result["review_count"] == 1
    decisions = _read_decisions(output_dir, "case")
    assert decisions.loc[0, "decision"] == "review"


def test_communication_duplicate_ids_block(monkeypatch):
    output_dir = _make_output_dir("test_dedupe_communication_block")
    guardrail = DedupeGuardrail(output_dir=output_dir)

    @contextmanager
    def _fake_connection():
        yield object()

    def _fake_read_sql(query: str, conn):  # noqa: ARG001
        if "fct_communication_calls" in query:
            return pd.DataFrame({"icalps_communication_id": [1, 1, 2]})
        if "fct_communication_notes" in query:
            return pd.DataFrame({"icalps_communication_id": [3, 4]})
        if "fct_communication_tasks" in query:
            return pd.DataFrame({"icalps_communication_id": [5]})
        return pd.DataFrame({"icalps_communication_id": [6]})

    monkeypatch.setattr("pipeline.dedupe.get_connection", _fake_connection)
    monkeypatch.setattr("pipeline.dedupe.pd.read_sql_query", _fake_read_sql)

    result = guardrail.execute("communication", dry_run=True)

    assert result["block_count"] == 2
    decisions = _read_decisions(output_dir, "communication")
    assert set(decisions["decision"]) == {"block"}
