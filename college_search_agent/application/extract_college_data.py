"""
One-time script to extract college data from the Excel snapshot and write it to
college_data/colleges.json.

Run from inside the college_search_agent/ directory:
    python -m application.extract_college_data
or directly:
    python application/extract_college_data.py

Excel layout (header at row index 2, data from row index 3):
  col 0 = (empty)
  col 1 = Course
  col 2 = College
  col 3 = Avg Board Cutoff  (decimal 0-1, e.g. 0.75 means 75%)
  col 4 = Avg Entrance Cutoff  (text range, e.g. "<2500 AIR")
  col 5 = Annual Fees  (text, e.g. "2.50L" = ₹2,50,000)
  col 6 = Brochure  (skipped)
  col 7 = KS Group with College  (skipped)
"""

import json
import os
import re
import openpyxl

# Paths relative to this file's location
_HERE = os.path.dirname(os.path.abspath(__file__))
_COLLEGE_DATA_DIR = os.path.join(_HERE, "..", "college_data")
_EXCEL_PATH = os.path.join(_COLLEGE_DATA_DIR, "KeyCaCo Colleges Snapshot.xlsx")
_JSON_PATH = os.path.join(_COLLEGE_DATA_DIR, "colleges.json")

# 0-based column indices
_COL_COURSE = 1
_COL_COLLEGE = 2
_COL_AVG_BOARD_CUTOFF = 3       # stored as decimal (0.75 = 75%)
_COL_AVG_ENTRANCE_CUTOFF = 4    # text like "<2500 AIR"
_COL_ANNUAL_FEES = 5             # text like "2.50L"

# Header is at row index 2 (two blank rows precede it); data starts at row index 3
_HEADER_ROW_INDEX = 2


def _to_str(value) -> str | None:
    """Convert a cell value to stripped string; return None if blank."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _board_cutoff_to_pct(value) -> float | None:
    """
    Convert the board cutoff cell value to a percentage (0-100).
    The Excel stores it as a decimal (e.g. 0.75 → 75.0).
    """
    if value is None:
        return None
    try:
        f = float(value)
        # Values stored as 0-1 fraction → convert to percentage
        if 0.0 < f <= 1.0:
            return round(f * 100, 2)
        # Already a percentage (shouldn't happen but handle gracefully)
        return round(f, 2)
    except (ValueError, TypeError):
        return None


def _fees_to_rupees(value) -> float | None:
    """
    Parse an annual-fees cell value to a numeric amount in rupees.
    Handles formats like "2.50L", "1.20L", "1.7L-2.7L" (range → lower bound),
    "250000", and bare numbers.  'L' / 'Lakh' suffix means × 100,000.
    For ranges, the lower bound is returned (conservative / affordable check).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Extract the first number (handles ranges like "1.7L-2.7L" → "1.7L")
    m = re.search(r"([\d,]+\.?\d*)\s*[Ll](?:akh)?s?", s)
    if m:
        numeric = float(m.group(1).replace(",", ""))
        return round(numeric * 100_000, 2)

    # Pure number (no suffix) – try the full string, then leading number
    m2 = re.match(r"([\d,]+\.?\d*)", s)
    if m2:
        try:
            return float(m2.group(1).replace(",", ""))
        except ValueError:
            pass

    return None


def extract(excel_path: str = _EXCEL_PATH, json_path: str = _JSON_PATH) -> list[dict]:
    """
    Read the Excel file and return a list of college dicts.
    Also writes the result to json_path.
    """
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    colleges = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        # Skip blank rows and the header row
        if idx <= _HEADER_ROW_INDEX:
            continue
        if all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        course = _to_str(row[_COL_COURSE])
        college = _to_str(row[_COL_COLLEGE])

        # Skip if neither course nor college is present
        if course is None and college is None:
            continue

        # Skip repeated column-header rows (section dividers in the Excel)
        if course == "Course" and college == "College":
            continue

        entry = {
            "course": course,
            "college": college,
            "avg_board_cutoff_pct": _board_cutoff_to_pct(row[_COL_AVG_BOARD_CUTOFF]),
            "avg_entrance_cutoff": _to_str(row[_COL_AVG_ENTRANCE_CUTOFF]),
            "annual_fees": _fees_to_rupees(row[_COL_ANNUAL_FEES]),
            "annual_fees_display": _to_str(row[_COL_ANNUAL_FEES]),
        }
        colleges.append(entry)

    wb.close()

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(colleges, f, indent=2, ensure_ascii=False)

    print(f"Extracted {len(colleges)} college records → {json_path}")
    return colleges


if __name__ == "__main__":
    extract()
