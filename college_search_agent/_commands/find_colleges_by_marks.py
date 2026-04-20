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
    """Find colleges the student is eligible for based on their board exam percentage"""

    class Input(BaseModel):
        """Parameters taken from user utterance."""

        marks: float = Field(
            default=_FLOAT_SENTINEL,
            description=(
                "The student board exam percentage (0-100). "
                "Only colleges whose board cutoff is at or below this value are returned. "
                "Example: 78 for 78%."
            ),
            examples=[75.0, 80.0, 92.0],
        )

        model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    class Output(BaseModel):
        colleges: str = Field(
            description="JSON list of colleges the student qualifies for based on their marks.",
            json_schema_extra={"used_by": ["search_colleges"]}
        )

    plain_utterances: List[str] = [
        "I scored 78% in boards, which colleges can I get into?",
        "My board marks are 85 percent, show me eligible colleges.",
        "I got 92% in 12th, what colleges are available for me?",
        "Which colleges accept students with 75 percent board marks?",
        "I have 80% marks, where can I apply?",
        "Show colleges I am eligible for with 70% board percentage.",
        "I got 88 percent in board exams, list matching colleges.",
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
                    response="Here are the colleges you are eligible for based on your marks:\n" + output.colleges
                )
            ],
        )

    def _process_command(self, workflow: Workflow, input: Signature.Input) -> Signature.Output:
        data = load_data()
        # Normalise fastworkflow sentinel to None
        marks = input.marks if (input.marks is not None and input.marks > 0) else None
        colleges = SearchColleges.invoke(data=data, marks=marks)
        return Signature.Output(colleges=colleges)
