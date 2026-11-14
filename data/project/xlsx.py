"""Minimal xlsx writer and reader on the standard library.

Written by hand instead of openpyxl so the file bytes are identical on every run: no clock in
the metadata, fixed zip timestamps, no compression (the output does not depend on the zlib version).
Cells are text or numbers; dates are ISO 8601 text, so they round-trip without float rounding.
"""
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

Cell = str | int | float | None
Sheets = list[tuple[str, list[list[Cell]]]]

_FIXED_TIME = (2026, 11, 13, 0, 0, 0)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{sheets}</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _sheet_xml(rows: list[list[Cell]]) -> str:
    widths = [0] * max(len(r) for r in rows)
    out = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{_col(c)}{r}"
            style = ' s="1"' if r == 1 else ""
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
                length = len(str(value))
            else:
                text = escape(str(value))
                cells.append(f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
                length = len(str(value))
            widths[c] = max(widths[c], length)
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{min(max(w + 2, 8), 60)}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(out)}</sheetData></worksheet>"
    )


def write_xlsx(path, sheets: Sheets) -> None:
    sheet_types = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    workbook_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets></workbook>"
    )
    rel_items = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    style_id = len(sheets) + 1
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rel_items}<Relationship Id="rId{style_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    )
    parts = [
        ("[Content_Types].xml", _CONTENT_TYPES.format(sheets=sheet_types)),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_rels),
        ("xl/styles.xml", _STYLES),
    ]
    for i, (_, rows) in enumerate(sheets, start=1):
        parts.append((f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows)))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name, text in parts:
            info = zipfile.ZipInfo(name, _FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            z.writestr(info, text.encode("utf-8"))


def read_xlsx(path) -> dict[str, list[list[Cell]]]:
    """Return {sheet name: rows}. Handles the cell kinds this module writes (inline text, numbers)
    and shared strings, so a file saved by Excel reads too."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")) for si in root.findall("m:si", _NS)]
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        rid_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        result: dict[str, list[list[Cell]]] = {}
        for sheet in workbook.find("m:sheets", _NS):
            root = ET.fromstring(z.read("xl/" + target[sheet.get(rid_key)]))
            rows: list[list[Cell]] = []
            for row in root.find("m:sheetData", _NS):
                values: list[Cell] = []
                for cell in row:
                    letters = "".join(ch for ch in cell.get("r") if ch.isalpha())
                    index = 0
                    for ch in letters:
                        index = index * 26 + ord(ch) - 64
                    while len(values) < index - 1:
                        values.append(None)
                    kind = cell.get("t")
                    if kind == "inlineStr":
                        value: Cell = "".join(t.text or "" for t in cell.iter(f"{{{_NS['m']}}}t"))
                    elif kind == "s":
                        value = shared[int(cell.find("m:v", _NS).text)]
                    else:
                        v = cell.find("m:v", _NS)
                        if v is None:
                            value = None
                        else:
                            number = float(v.text)
                            value = int(number) if number.is_integer() else number
                    values.append(value)
                rows.append(values)
            result[sheet.get("name")] = rows
    return result
