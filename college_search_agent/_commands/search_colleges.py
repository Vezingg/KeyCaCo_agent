import sys
from typing import List, Optional

import fastworkflow
from pydantic import BaseModel, Field, ConfigDict
from fastworkflow.workflow import Workflow
from fastworkflow import CommandOutput, CommandResponse

# Domain helpers
from ..application.college_data_loader import load_data
from ..tools.search_colleges import SearchColleges

_FLOAT_SENTINEL = -sys.float_info.max


class Signature:
    """Search for colleges by course, board marks, annual fee budget, or any combination"""

    class Input(BaseModel):
        """Parameters taken from user utterance."""

        course: Optional[str] = Field(
            default=None,
            description=(
                "Course name to filter colleges by (partial match, case-insensitive). "
                "Examples: \'BBA\', \'B.Tech\', \'B.Com\', \'B.Sc\'. "
                "Leave unset if the user did not mention a specific course."
            ),
            examples=["BBA", "B.Tech", "B.Com"],
            json_schema_extra={"available_from": ["find_colleges_by_course"]},
        )

        marks: Optional[float] = Field(
            default=None,
            description=(
                "The student board exam percentage (0-100). "
                "Only colleges whose cutoff is at or below this value are returned. "
                "Leave unset if the user did not mention their marks."
            ),
            examples=[75.0, 85.5, 92.0],
            json_schema_extra={"available_from": ["find_colleges_by_marks"]},
        )

        max_annual_fees: Optional[float] = Field(
            default=None,
            description=(
                "Maximum annual fees in rupees the student can afford. "
                "Convert shorthand: 1.5L to 150000, 2 lakhs to 200000. "
                "Leave unset if the user did not mention a budget."
            ),
            examples=[150000, 250000, 300000],
            json_schema_extra={"available_from": ["find_colleges_by_fees"]},
        )

        model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    class Output(BaseModel):
        colleges: str = Field(
            description=(
                "JSON list of college records matching the given filters, "
                "each with course, college name, board cutoff percentage, "
                "entrance cutoff text, and annual fees."
            )
        )

    plain_utterances: List[str] = [
        "Which colleges offer BBA?",
        "Show me all B.Tech colleges.",
        "I scored 78% in boards, which colleges can I get into?",
        "I can pay up to 1.5 lakh per year, show me colleges.",
        "I have 80% board marks and a budget of 2 lakhs per year, where can I apply?",
        "Show me BBA colleges with fees under 1 lakh.",
        "Which B.Tech colleges accept 75 percent board marks?",
        "List colleges with annual fees below 2 lakh.",
        "I got 90% boards and can pay 3L, what are my options?",
        "Show me all colleges available.",
    ]

    template_utterances: List[str] = []

    @staticmethod
    def generate_utterances(workflow: fastworkflow.Workflow, command_name: str) -> List[str]:
        utterance_definition = fastworkflow.RoutingRegistry.get_definition(workflow.folderpath)
        utterances_obj = utterance_definition.get_command_utterances(command_name)

        from fastworkflow.train.generate_synthetic import generate_diverse_utterances

        return generate_diverse_utterances(utterances_obj.plain_utterances, command_name)


class ResponseGenerator:
    def __call__(
        self,
        workflow: Workflow,
        command: str,
        command_parameters: Signature.Input,
    ) -> CommandOutput:
        output = self._process_command(workflow, command_parameters)
        return CommandOutput(
            workflow_id=workflow.id,
            command_responses=[
                CommandResponse(
                    response="Here are the colleges matching your criteria:\n" + output.colleges
                )
            ],
        )

    def _process_command(self, workflow: Workflow, input: Signature.Input) -> Signature.Output:
        data = load_data()
        # Normalise fastworkflow float sentinels to None
        marks = input.marks if (input.marks is not None and input.marks > 0) else None
        max_annual_fees = (
            input.max_annual_fees
            if (input.max_annual_fees is not None and input.max_annual_fees > 0)
            else None
        )
        colleges = SearchColleges.invoke(
            data=data,
            course=input.course,
            marks=marks,
            max_annual_fees=max_annual_fees,
        )
        return Signature.Output(colleges=colleges)
