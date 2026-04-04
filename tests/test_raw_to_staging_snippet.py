from __future__ import annotations

from numbers import Integral

import pandas as pd

from pipeline.raw_to_staging_snippet import DateFieldSpec, normalize_frame_for_staging, serialize_date_value


def test_serialize_date_value_supports_text_and_excel_serial_inputs():
    assert serialize_date_value("2025-06-03 09:45:51", output_format="iso_datetime") == "2025-06-03 09:45:51"
    assert serialize_date_value("2020-05-03", output_format="iso_date") == "2020-05-03"
    assert serialize_date_value("43954", output_format="iso_date") == "2020-05-03"


def test_normalize_frame_for_staging_applies_shared_cleanup_and_lowercases_columns():
    frame = pd.DataFrame(
        [
            {
                "Case_CaseId": "1",
                "Case_Description": "Questionnaire client Ã©tape\r\n",
                "Case_CloseDate": "2019-04-09 13:42:00",
                "Case_Priority": "Normal",
            }
        ]
    )

    normalized = normalize_frame_for_staging(
        frame,
        text_fields=["Case_Description"],
        date_fields=[DateFieldSpec("Case_CloseDate", "epoch_millis")],
        rename_map={"Case_CaseId": "icalps_ticket_id"},
    )

    assert normalized.columns.tolist() == [
        "icalps_ticket_id",
        "case_description",
        "case_closedate",
        "case_priority",
    ]
    assert normalized.loc[0, "case_description"] == "Questionnaire client étape"
    assert isinstance(normalized.loc[0, "case_closedate"], Integral)
    assert normalized.loc[0, "case_priority"] == "Normal"
