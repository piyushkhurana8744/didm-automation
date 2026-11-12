from io import BytesIO
from zipfile import ZipFile

import pytest

from app.excel_leads import parse_excel, sample_excel
from app.main import _transcript_text


def workbook(rows):
    cells = []
    for row_number, row in enumerate(rows, 1):
        content = []
        for column, value in enumerate(row, 1):
            letters, n = "", column
            while n:
                n, rem = divmod(n - 1, 26)
                letters = chr(65 + rem) + letters
            content.append(f'<c r="{letters}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>')
        cells.append(f'<row r="{row_number}">{"".join(content)}</row>')
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(cells)}</sheetData></worksheet>')
    return out.getvalue()


def test_excel_parser_accepts_aliases_and_rejects_bad_or_duplicate_numbers():
    leads, rejected = parse_excel(workbook([
        ["Naam", "Mobile Number", "Course"],
        ["Riya", "9810512345", "MBA"],
        ["Bad", "123", "MBA"],
        ["Again", "+91 98105 12345", "MBA"],
    ]))
    assert leads == [{"name": "Riya", "phone": "+919810512345", "course": "MBA", "call": "YES"}]
    assert [x["reason"] for x in rejected] == ["Invalid Indian phone number", "Duplicate phone number"]


def test_excel_parser_requires_name_and_phone_headers():
    with pytest.raises(ValueError, match="lead_name aur phone"):
        parse_excel(workbook([["Person", "Address"], ["Riya", "Delhi"]]))


def test_transcript_normalizes_provider_turns():
    payload = {"interaction_transcript": [{"role": "agent", "en_text": "Hello"},
                                           {"role": "user", "text": "Hi"}]}
    assert _transcript_text(payload) == "agent: Hello\nuser: Hi"


def test_downloadable_sample_is_valid_and_uses_sarvam_lead_name_header():
    leads, rejected = parse_excel(sample_excel())
    assert rejected == []
    assert leads[0]["name"] == "Riya Sharma"
    assert leads[0]["phone"] == "+919810512345"
