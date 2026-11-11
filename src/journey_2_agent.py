from typing import Literal

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from openai import APIConnectionError
from pydantic import BaseModel, Field

from file_loader import MANUAL_PATH, load_manual
from journey_1_agent import MAX_STEPS, RETRY_MESSAGE, STEP_LIMIT_MESSAGE
from models import Database, Line, ManualSection
from search import DataLayer
from icecream import ic

NOT_ON_ACCOUNT_MESSAGE: str = "I cannot find that phone number on an account. Please give a phone number that is on the account."

SYSTEM_PROMPT: str = """You answer telecom customers' technical support questions using only the manual.

The manual index below lists each section by its key and heading path. Call get_manual_section with a key to read that section's text.

Rules:
- Use only the manual text. Do not use general knowledge.
- Phrase each step as something the customer does on their phone. Do not write tool names such as toggle_airplane_mode(). The customer cannot run them.
- Cite the keys of the sections the answer uses, in the citations field of FinalAnswer.
- If a step needs a SIM PIN or PUK code, or the manual says to escalate, say the case needs technical support.
- If the manual does not cover the question, say it is not covered by the manual and offer to transfer the customer to a human agent. Do not guess. Use outcome not_covered.
- When line context is given, it comes from the customer's account. If the line is suspended, say so. Lines are suspended for an overdue bill or a contract end date in the past.
- Call FinalAnswer once.
"""


class AgentRequest(BaseModel):
    question: str
    phone_number: str | None = None


class FinalAnswer(BaseModel):
    """Give the answer to the customer. Call this once, with the keys of the manual sections the answer uses."""

    reasoning: str = Field(description="One sentence on why you chose this outcome.")
    answer: str
    outcome: Literal["answered", "not_covered"]
    citations: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    reasoning: str = ""
    answer: str
    outcome: Literal["answered", "not_covered", "not_on_account", "unavailable", "step_limit"]
    citations: list[str] = Field(default_factory=list)


class GetManualSection(BaseModel):
    """Get the full text of one manual section, by its key from the index, such as "S12"."""

    section_key: str


def describe_index(sections: dict[str, ManualSection]) -> str:
    return "\n".join(f"{section.key}: {section.path}" for section in sections.values())


def describe_line(line: Line) -> str:
    if line.status != "Suspended":
        return f"Line {line.line_id} ({line.phone_number}) has status {line.status}."
    return f"Line {line.line_id} ({line.phone_number}) is Suspended, with suspension start date {line.suspension_start_date}."


class Agent:
    """Answers troubleshooting questions from the manual. The manual and the line data are loaded once, at construction."""

    def __init__(self, db: Database, llm: BaseChatModel) -> None:
        self._db: Database = db
        self._sections: dict[str, ManualSection] = load_manual(MANUAL_PATH).sections
        self._model: Runnable[LanguageModelInput, AIMessage] = llm.bind_tools(
            [FinalAnswer, GetManualSection], tool_choice="required"
        )

    async def answer(self, request: AgentRequest) -> AgentResponse:
        line_context: str = ""
        if request.phone_number is not None:
            lines: list[Line] = DataLayer.find_line_by_phone(self._db, request.phone_number).lines
            if not lines:
                return AgentResponse(answer=NOT_ON_ACCOUNT_MESSAGE, outcome="not_on_account")
            line_context = describe_line(lines[0])

        messages: list[BaseMessage] = [
            SystemMessage(f"{SYSTEM_PROMPT}\nManual index:\n\n{describe_index(self._sections)}"),
            HumanMessage(f"{line_context}\n\n{request.question}".strip()),
        ]
        try:
            for _ in range(MAX_STEPS):
                reply: AIMessage = await self._model.ainvoke(messages)
                messages.append(reply)
                for call in reply.tool_calls:
                    if call["name"] == FinalAnswer.__name__:
                        final: FinalAnswer = FinalAnswer.model_validate(call["args"])
                        ic(f"final: ",final)
                        paths: list[str] = [self._sections[key].path for key in final.citations]
                        return AgentResponse(
                            reasoning=final.reasoning,
                            answer=final.answer,
                            outcome=final.outcome,
                            citations=paths,
                        )
                    if call["name"] == GetManualSection.__name__:
                        request_section: GetManualSection = GetManualSection.model_validate(call["args"])
                        section: ManualSection = self._sections[request_section.section_key]
                        messages.append(ToolMessage(content=section.text, tool_call_id=call["id"]))
        except APIConnectionError:
            return AgentResponse(answer=RETRY_MESSAGE, outcome="unavailable")
        return AgentResponse(answer=STEP_LIMIT_MESSAGE, outcome="step_limit")
