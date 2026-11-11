import os
from typing import Literal

from icecream import ic
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from openai import APIConnectionError
from pydantic import BaseModel, Field

from models import BillStatus, Database
from search import DataLayer

MODEL_BASE_URL: str = os.environ["LLM_BASE_URL"]
EMBED_BASE_URL: str = os.environ["EMBED_BASE_URL"]
EMBED_MODEL: str = os.environ["EMBED_MODEL"]
MODEL_NAME: str = "qwen2.5-7b"
MAX_STEPS: int = 6

RETRY_MESSAGE: str = "The assistant is unavailable right now. Please try again in a few minutes."
STEP_LIMIT_MESSAGE: str = "I could not finish answering. Please ask a more specific question."

SYSTEM_PROMPT: str = """You answer questions about a telecom customer's account: bills, plan, lines, and data usage.

Rules:
- State only facts returned by the tools. Do not use general knowledge.
- Quote bill and line IDs in your answer.
- Give no subjective advice.
- If the data does not contain the answer, say so.
- If the question does not say whose account it is, ask for a customer ID, phone number, or name.
- If a customer cannot be found, say you cannot find the account. Do not guess.
- To find what a customer owes, list all their bills with no status filter, then report the bills that are not Paid. For each one, give the bill ID, status, amount, and due date.
- When you have the answer, call the FinalAnswer tool. Set outcome to answered, not_found, or needs_customer.
- Use answered when the customer exists, even if the answer is an empty list, such as a customer with no lines.
- Use not_found only when no customer matches the ID, phone number, or name.
- Use needs_customer when the question does not say whose account it is. In that case, call FinalAnswer right away and ask for a customer ID, phone number, or name. Never call a search tool without one of those. If the question has no customer ID, phone number, or name, the outcome is needs_customer, never not_found.
"""


class AgentRequest(BaseModel):
    question: str


class FinalAnswer(BaseModel):
    """Give the final answer to the customer. Call this once, with the IDs of the bills and lines the answer uses."""

    reasoning: str = Field(
        description="One or two sentences on why you chose this outcome, citing the tool results you used."
    )
    answer: str
    outcome: Literal["answered", "not_found", "needs_customer"]
    bill_ids: list[str] = Field(default_factory=list)
    line_ids: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    reasoning: str = ""
    answer: str
    outcome: Literal["answered", "not_found", "needs_customer", "unavailable", "step_limit"]
    bill_ids: list[str] = Field(default_factory=list)
    line_ids: list[str] = Field(default_factory=list)


def build_tools(db: Database) -> list[BaseTool]:
    @tool
    def find_customer_by_id(customer_id: str) -> str:
        """Find one customer by customer ID, such as "C1002"."""
        return DataLayer.find_customer_by_id(db, customer_id).model_dump_json()

    @tool
    def find_customers_by_phone(phone_number: str) -> str:
        """Find customers whose account phone number matches."""
        return DataLayer.find_customers_by_phone(db, phone_number).model_dump_json()

    @tool
    def find_customers_by_name(name: str) -> str:
        """Find customers whose full name contains the given text, ignoring case."""
        return DataLayer.find_customers_by_name(db, name).model_dump_json()

    @tool
    def find_line_by_id(line_id: str) -> str:
        """Find one line by line ID, such as "L1004"."""
        return DataLayer.find_line_by_id(db, line_id).model_dump_json()

    @tool
    def get_customer_lines(customer_id: str) -> str:
        """List all lines on a customer's account, with their plans and devices."""
        return DataLayer.get_customer_lines(db, customer_id).model_dump_json()

    @tool
    def find_bill_by_id(bill_id: str) -> str:
        """Find one bill by bill ID, such as "B1005"."""
        return DataLayer.find_bill_by_id(db, bill_id).model_dump_json()

    @tool
    def get_customer_bills(customer_id: str, status: BillStatus | None = None) -> str:
        """List a customer's bills. Leave status out to get all bills. Pass status only to keep bills with that one status."""
        return DataLayer.get_customer_bills(db, customer_id, status).model_dump_json()

    @tool
    def find_plan_by_id(plan_id: str) -> str:
        """Find one plan by plan ID, such as "P1002"."""
        return DataLayer.find_plan_by_id(db, plan_id).model_dump_json()

    tools: list[BaseTool] = [
        find_customer_by_id,
        find_customers_by_phone,
        find_customers_by_name,
        find_line_by_id,
        get_customer_lines,
        find_bill_by_id,
        get_customer_bills,
        find_plan_by_id,
    ]
    for t in tools:
        t.handle_validation_error = True
    return tools


class Agent:
    """Answers customer questions. The database, tools and bound model are set up once, at construction."""

    def __init__(self, db: Database, llm: BaseChatModel) -> None:
        tools: list[BaseTool] = build_tools(db)
        self._tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools}
        self._model: Runnable[LanguageModelInput, AIMessage] = llm.bind_tools(
            [FinalAnswer, *tools], tool_choice="required"
        )

    async def answer(self, request: AgentRequest) -> AgentResponse:
        ic(self._model)
        messages: list[BaseMessage] = [SystemMessage(SYSTEM_PROMPT), HumanMessage(request.question)]
        customer_found: bool = False
        try:
            for _ in range(MAX_STEPS):
                reply: AIMessage = await self._model.ainvoke(messages)
                messages.append(reply)
                for call in reply.tool_calls:
                    if call["name"] == FinalAnswer.__name__:
                        final: FinalAnswer = FinalAnswer.model_validate(call["args"])
                        if customer_found and final.outcome != "needs_customer":
                            final.outcome = "answered"
                        return AgentResponse(**final.model_dump())
                    result: ToolMessage = await self._tools_by_name[call["name"]].ainvoke(call)
                    if result.status == "success" and Database.model_validate_json(result.content).customers:
                        customer_found = True
                    messages.append(result)
        except APIConnectionError:
            return AgentResponse(answer=RETRY_MESSAGE, outcome="unavailable")
        return AgentResponse(answer=STEP_LIMIT_MESSAGE, outcome="step_limit")
