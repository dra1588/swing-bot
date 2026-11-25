import io
import zipfile

from swing_bot import sec_inspect


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tISSUERTRADINGSYMBOL\nA1\t02-JAN-2015\tXYZ\nA2\t03-JAN-2015\tABC\n")
        z.writestr("NONDERIV_TRANS.tsv", "ACCESSION_NUMBER\tTRANS_CODE\tTRANS_SHARES\nA1\tP\t100\n")
        z.writestr("FORM345_metadata.json", "{}")
    return buf.getvalue()


def test_describe_lists_tables_columns_and_rows():
    info = sec_inspect.describe(make_zip())
    assert info["SUBMISSION.tsv"]["rows"] == 2
    assert info["SUBMISSION.tsv"]["columns"] == ["ACCESSION_NUMBER", "FILING_DATE", "ISSUERTRADINGSYMBOL"]
    assert info["NONDERIV_TRANS.tsv"]["sample"][0]["TRANS_CODE"] == "P"
    assert info["FORM345_metadata.json"]["rows"] is None


def test_fetch_declares_user_agent_and_tries_fallback_urls(monkeypatch):
    seen = []

    class R:
        def __init__(self, code, content=b""):
            self.status_code, self.content = code, content

    class S:
        headers = {}
        def get(self, url, timeout=0):
            seen.append((url, dict(self.headers)))
            return R(200, make_zip()) if "dera" in url and "files" in url else R(404)
    monkeypatch.setenv("SEC_USER_AGENT", "test-project test@example.invalid")
    blob = sec_inspect.fetch("2015q1", session=S())
    assert blob[:2] == b"PK" and len(seen) == 2
    assert all(h["User-Agent"] == "test-project test@example.invalid" for _, h in seen)


def test_blank_user_agent_variable_falls_back_to_a_declared_default(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "")
    seen = []

    class R:
        status_code, content = 200, make_zip()

    class S:
        headers = {}
        def get(self, url, timeout=0):
            seen.append(dict(self.headers)); return R()
    sec_inspect.fetch("2015q1", session=S())
    assert seen[0]["User-Agent"].strip() != ""
