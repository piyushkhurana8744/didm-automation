"""Small, durable Excel inbox for the legacy lead dialler."""
import uuid
from io import BytesIO
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from sqlalchemy import delete, select

from .db import ImportedLead, SessionLocal, get_flag, set_flag
from .leads import COL, to_e164

HEADER_ALIASES = {
    "lead_name": "name", "lead name": "name", "name": "name", "naam": "name",
    "phone": "phone", "mobile": "phone",
    "phone number": "phone", "mobile number": "phone", "number": "phone",
    "course": "course", "course interest": "course", "source": "source",
    "city": "city", "note": "note", "notes": "note", "email": "email",
}

SAMPLE_ROWS = [
    ["lead_name", "phone", "course", "source", "city", "note"],
    ["Riya Sharma", "9810512345", "Digital Marketing", "Website", "Delhi", "Interested in weekend batch"],
    ["Aman Verma", "+91 98765 43210", "MBA", "Facebook", "Noida", "Call after 4 PM"],
]


def parse_excel(content: bytes, max_rows: int = 5000) -> tuple[list[dict], list[dict]]:
    """Return valid lead dictionaries and rejected-row explanations."""
    try:
        raw_rows = _xlsx_rows(content, max_rows + 1)
    except (BadZipFile, KeyError, ET.ParseError, ValueError) as exc:
        raise ValueError("File valid .xlsx workbook nahi hai.") from exc
    if not raw_rows:
        raise ValueError("Excel file khaali hai.")
    header, rows = raw_rows[0], raw_rows[1:]
    mapped = {}
    for i, value in enumerate(header):
        key = HEADER_ALIASES.get(str(value or "").strip().lower())
        if key and key not in mapped:
            mapped[key] = i
    if "name" not in mapped or "phone" not in mapped:
        raise ValueError("Header row mein lead_name aur phone columns zaroori hain.")
    accepted, rejected, seen = [], [], set()
    for excel_row, values in enumerate(rows, start=2):
        if excel_row > max_rows + 1:
            raise ValueError(f"Ek upload mein maximum {max_rows} leads allowed hain.")
        data = {key: str(values[pos] or "").strip() if pos < len(values) else "" for key, pos in mapped.items()}
        if not any(data.values()):
            continue
        phone = to_e164(data.get("phone", ""))
        if not phone:
            rejected.append({"row": excel_row, "reason": "Invalid Indian phone number"})
            continue
        if phone in seen:
            rejected.append({"row": excel_row, "reason": "Duplicate phone number"})
            continue
        seen.add(phone)
        data["phone"], data["call"] = phone, "YES"
        accepted.append(data)
    if not accepted:
        raise ValueError("Koi valid lead nahi mili.")
    return accepted, rejected


def _xlsx_rows(content: bytes, limit: int) -> list[list[str]]:
    """Read the first XLSX worksheet with the standard library (values only)."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(BytesIO(content)) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(ns + "t"))
                      for item in root.iter(ns + "si")]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        first = workbook.find(".//" + ns + "sheet")
        if first is None:
            return []
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(r.attrib["Target"] for r in relationships
                      if r.attrib.get("Id") == first.attrib.get(rel_id))
        path = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target.lstrip("/")
        sheet = ET.fromstring(archive.read(path))
        result = []
        for row in sheet.iter(ns + "row"):
            values = {}
            for cell in row.iter(ns + "c"):
                ref = cell.attrib.get("r", "A1")
                letters = "".join(ch for ch in ref if ch.isalpha())
                index = 0
                for ch in letters.upper():
                    index = index * 26 + ord(ch) - 64
                value_node = cell.find(ns + "v")
                inline = cell.find(ns + "is")
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.attrib.get("t") == "inlineStr" and inline is not None:
                    value = "".join(n.text or "" for n in inline.iter(ns + "t"))
                values[index - 1] = value
            width = max(values, default=-1) + 1
            result.append([values.get(i, "") for i in range(width)])
            if len(result) > limit:
                raise ValueError("row limit")
        return result


def sample_excel() -> bytes:
    """Create a dependency-free Excel template users can fill and upload."""
    cells = []
    for row_number, row in enumerate(SAMPLE_ROWS, 1):
        row_cells = []
        for column, value in enumerate(row, 1):
            letters, n = "", column
            while n:
                n, remainder = divmod(n - 1, 26)
                letters = chr(65 + remainder) + letters
            row_cells.append(f'<c r="{letters}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        cells.append(f'<row r="{row_number}">{"".join(row_cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(cells)}</sheetData></worksheet>')
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Leads" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


class DatabaseLeadSheet:
    """Sheet-compatible adapter; an active Excel upload wins over Google Sheets."""
    def __init__(self, fallback=None):
        self.fallback = fallback

    def _upload_id(self, session):
        return get_flag(session, "active_excel_upload", "")

    def has_active_import(self) -> bool:
        with SessionLocal() as session:
            return bool(self._upload_id(session))

    def read_rows(self):
        with SessionLocal() as session:
            upload_id = self._upload_id(session)
            if upload_id:
                rows = session.scalars(select(ImportedLead).where(ImportedLead.upload_id == upload_id)
                                       .order_by(ImportedLead.sheet_row)).all()
                return [(r.sheet_row, [r.data.get(k, "") for k, _ in sorted(COL.items(), key=lambda x: x[1])])
                        for r in rows]
        return self.fallback.read_rows() if self.fallback else []

    def update_row(self, row, updates):
        with SessionLocal() as session:
            upload_id = self._upload_id(session)
            if upload_id:
                lead = session.scalars(select(ImportedLead).where(
                    ImportedLead.upload_id == upload_id, ImportedLead.sheet_row == row)).first()
                if not lead:
                    raise LookupError(f"Imported row {row} not found")
                lead.data = {**lead.data, **{k: str(v) for k, v in updates.items()}}
                session.commit()
                return
        if not self.fallback:
            raise RuntimeError("No active Excel upload or Google Sheet")
        self.fallback.update_row(row, updates)


def save_upload(leads: list[dict]) -> str:
    upload_id = str(uuid.uuid4())
    with SessionLocal() as session:
        # Old imports are operational data, not call history; retain only the current set.
        session.execute(delete(ImportedLead))
        session.add_all([ImportedLead(upload_id=upload_id, sheet_row=i + 2, data=data)
                         for i, data in enumerate(leads)])
        session.commit()
        set_flag(session, "active_excel_upload", upload_id)
    return upload_id
