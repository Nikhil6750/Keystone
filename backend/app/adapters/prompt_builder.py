"""Deterministic prompt construction shared by all local CLI agent adapters."""

import json
from dataclasses import dataclass

from app.adapters.exceptions import AgentConfigurationError
from app.engine.executor import StepExecutionRequest


@dataclass(frozen=True)
class PromptBuilder:
    """Builds one deterministic, JSON-safe prompt string for a step execution request."""

    max_prompt_characters: int

    def build(self, request: StepExecutionRequest) -> str:
        """Build the prompt, rejecting it as `AgentConfigurationError` if oversized.

        Structured values are JSON-serialized (never Python `repr`/`str`), and
        `previous_step_outputs` is rendered as an explicitly ordered list so
        step ordering survives serialization.
        """
        previous_outputs = [
            {"step_id": step_id, "output": output}
            for step_id, output in request.previous_step_outputs.items()
        ]
        context = {
            "workflow_id": request.workflow_id,
            "step_id": request.step_id,
            "step_name": request.step_name,
            "agent_type": request.agent_type,
            "workflow_input": request.workflow_input,
            "step_input": request.step_input,
            "previous_step_outputs": previous_outputs,
        }
        prompt = (
            "You are executing one step of an automated workflow. Using the "
            "JSON context below, return one useful, concise result for this "
            "step.\n\nContext:\n" + json.dumps(context, indent=2)
        )
        if len(prompt) > self.max_prompt_characters:
            raise AgentConfigurationError(
                f"prompt exceeds the configured maximum of {self.max_prompt_characters} characters"
            )
        return prompt
