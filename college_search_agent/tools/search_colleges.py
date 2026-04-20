import json
from typing import Any, Optional


class SearchColleges:
    """
    Tool to search colleges by any combination of:
    - course name (partial, case-insensitive)
    - board exam percentage (student's % must meet or exceed the cutoff)
    - max annual fees budget

    All filters are optional. A college passes a filter if:
    - No filter value given → all colleges pass that filter
    - Filter value given but college's corresponding field is null → college passes (no restriction)
    - Filter value given and field has a value → normal comparison applies
    """

    @staticmethod
    def invoke(
        data: list[dict[str, Any]],
        course: Optional[str] = None,
        marks: Optional[float] = None,
        max_annual_fees: Optional[float] = None,
    ) -> str:
        """
        Search colleges by any combination of course, board marks, and fee budget.
        All parameters are optional — at least one should be provided.

        Args:
            data:            List of college dicts from college_data_loader.load_data().
            course:          Course name to filter by (partial, case-insensitive).
                             e.g. "BBA", "B.Tech", "B.Com"
            marks:           Student's board exam percentage (0-100).
                             Colleges whose cutoff exceeds this value are excluded.
            max_annual_fees: Maximum annual fees in rupees.
                             Colleges whose fees exceed this value are excluded.

        Returns:
            JSON string of matching college records, or a friendly message if none found.
        """
        results = []
        for college in data:
            # --- Course filter (partial, case-insensitive) ---
            if course is not None:
                college_course = college.get("course") or ""
                if course.lower().strip() not in college_course.lower():
                    continue

            # --- Board marks filter ---
            if marks is not None:
                cutoff = college.get("avg_board_cutoff_pct")
                # null cutoff -> no restriction for that college
                if cutoff is not None and marks < cutoff:
                    continue

            # --- Fees filter ---
            if max_annual_fees is not None:
                fees = college.get("annual_fees")
                # null fees -> no restriction for that college
                if fees is not None and fees > max_annual_fees:
                    continue

            results.append(college)

        if not results:
            parts = []
            if course:
                parts.append(f"course={course}")
            if marks is not None:
                parts.append(f"board marks={marks}%")
            if max_annual_fees is not None:
                parts.append(f"max annual fees=Rs{max_annual_fees:,.0f}")
            criteria = ", ".join(parts) if parts else "given criteria"
            return f"No colleges found matching your criteria ({criteria})."

        return json.dumps(results, indent=2, ensure_ascii=False)

    @staticmethod
    def get_info() -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "search_colleges",
                "description": (
                    "Search for colleges using any combination of course name, "
                    "board exam percentage, and annual fee budget. All filters are optional. "
                    "Returns matching college records with course, college name, cutoffs, "
                    "and annual fees."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "course": {
                            "type": "string",
                            "description": (
                                "Course name to filter by (partial match, case-insensitive). "
                                "Examples: 'BBA', 'B.Tech', 'B.Com', 'B.Sc'."
                            ),
                        },
                        "marks": {
                            "type": "number",
                            "description": (
                                "Student's board exam percentage (0-100). "
                                "Only colleges whose cutoff is at or below this value are returned. "
                                "Example: 75.5 for 75.5%."
                            ),
                        },
                        "max_annual_fees": {
                            "type": "number",
                            "description": (
                                "Maximum annual fees in rupees the student can afford. "
                                "Convert shorthand: '1.5L' -> 150000, '2 lakhs' -> 200000. "
                                "Omit if there is no budget constraint."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        }
