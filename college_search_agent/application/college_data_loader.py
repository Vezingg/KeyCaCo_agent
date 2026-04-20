"""
Loads the pre-extracted college data from college_data/colleges.json.
Run application/extract_college_data.py once to generate that file.
"""

import json
import os
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_JSON_PATH = os.path.join(_HERE, "..", "college_data", "colleges.json")


def load_data() -> list[dict[str, Any]]:
    """Return the list of college records loaded from colleges.json."""
    with open(_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
