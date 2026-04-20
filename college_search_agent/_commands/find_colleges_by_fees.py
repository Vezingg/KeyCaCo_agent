import sys
from typing import List, Optional

import fastworkflow
from pydantic import BaseModel, Field, ConfigDict
from fastworkflow.workflow import Workflow
from fastworkflow import CommandOutput, CommandResponse

from ..application.college_data_loader import load_data
from ..tools.search_colleges import SearchColleges

_FLOAT_SENTINEL = -sys.float_info.max


class Signature:
    """Find colleges within the student's annual fee budget"""

    class Input(BaseModel):
        """Parameters taken from user utterance."""

        max_annual_fees: float = Field(
            default=_FLOAT_SENTINEL,
            description=(
                "Maximum annual fees in rupees the student can afford. "
                "Convert shorthand: '1.5L' -> 150000, '2 lakhs' -> 200000, '50k' -> 50000. "
                "Example: 150000 for 1.5 lakh per year."
            ),
            examples=[100000, 150000, 250000],
        )

        model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    class Output(BaseModel):
        colleges: str = Field(
            description="JSON list of colleges within the student's annual fee budget.",
            json_schema_extra={"used_by": ["search_colleges"]}
        )

    plain_utterances: List[str] = [
        "I can pay up to 1.5 lakh per year, show me colleges.",
        "Which colleges have annual fees below 2 lakh?",
        "Show me colleges under 1 lakh annual fees.",
        "My budget is 2.5 lakh per year, what colleges are affordable?",
        "List colleges with fees less than 3 lakhs.",
        "I can only afford 50 thousand per year, any colleges?",
        "Show colleges within my budget of 2 lakhs annual fees.",
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
                    response="Here are the colleges within your fee budget:\n" + output.colleges
                )
            ],
        )

    def _process_command(self, workflow: Workflow, input: Signature.Input) -> Signature.Output:
        data = load_data()
        # Normalise fastworkflow sentinel to None
        max_annual_fees = (
            input.max_annual_fees
            if (input.max_annual_fees is not None and input.max_annual_fees > 0)
            else None
        )
        colleges = SearchColleges.invoke(data=data, max_annual_fees=max_annual_fees)
        return Signature.Output(colleges=colleges)
