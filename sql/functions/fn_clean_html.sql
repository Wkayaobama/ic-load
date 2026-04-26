-- fn_clean_html — strip HTML tags and content using BeautifulSoup.
--
-- Replaces the regexp_replace implementation. Uses plpython3u + bs4 4.14.3
-- installed at /var/lib/postgresql/.local/lib/python3.10/site-packages (Apr 2026).
-- sys.path insert is required because bs4 was installed via --user pip.
--
-- Called by: normalise_communication (comm_subject, comm_note),
--            normalise_contact (pers_title), normalise_opportunity (icalps_dealnotes).
-- Idempotent.

CREATE OR REPLACE FUNCTION staging.fn_clean_html(txt text)
RETURNS text
LANGUAGE plpython3u
IMMUTABLE
AS $$
if txt is None:
    return None
import sys
_bs4_path = '/var/lib/postgresql/.local/lib/python3.10/site-packages'
if _bs4_path not in sys.path:
    sys.path.insert(0, _bs4_path)
from bs4 import BeautifulSoup
cleaned = BeautifulSoup(txt, 'html.parser').get_text(separator=' ', strip=True)
return cleaned if cleaned else None
$$;

COMMENT ON FUNCTION staging.fn_clean_html(text) IS
'Strip HTML tags using BeautifulSoup. NULL-safe, idempotent.';
