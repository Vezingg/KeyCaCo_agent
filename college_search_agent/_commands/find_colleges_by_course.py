from typing import List

import fastworkflow
from pydantic import BaseModel, Field, ConfigDict
from fastworkflow.workflow import Workflow
from fastworkflow import CommandOutput, CommandResponse

from ..application.college_data_loader import load_data
from ..tools.search_colleges import SearchColleges


class Signature:
    """Find colleges that offer a specific course (e.g. BBA, B.Tech, B.Com, B.Sc)"""

    class Input(BaseModel):
        """Parameters taken from user utterance."""

        course: str = Field(
            default="NOT_FOUND",
            description=(
                "The course name to search for (partial match, case-insensitive). "
                "Examples: 'BBA', 'B.Tech', 'B.Com', 'B.Sc (Finance)'."
            ),
            examples=["BBA", "B.Tech", "B.Com"],
        )

        model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    class Output(BaseModel):
        colleges: str = Field(
            description="JSON list of colleges offering the requested course.",
            json_schema_extra={"used_by": ["search_colleges"]}
        )

    plain_utterances: List[str] = [
        "Which colleges offer BBA?",
        "Show me all B.Tech colleges.",
        "Which colleges have a B.Com program?",
        "List all colleges that offer B.Sc Finance.",
        "What courses are available at which colleges?",
        "I want to study BBA, which colleges can I apply to?",
        "Show colleges with B.Tech course.",
        "Which college provides B.Com?",
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
                    response="Here are the colleges offering that course:\n" + output.colleges
                )
            ],
        )

    def _process_command(self, workflow: Workflow, input: Signature.Input) -> Signature.Output:
        data = load_data()
        course = None if input.course == "NOT_FOUND" else input.course
        colleges = SearchColleges.invoke(data=data, course=course)
        return Signature.Output(colleges=colleges)
