import json
import time
from datetime import date
from typing import Literal

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from openai import APIConnectionError
from pydantic import BaseModel, Field

from journey_1_agent import RETRY_MESSAGE, STEP_LIMIT_MESSAGE
from models import Bill, Database, PaymentMethod
from payments import OPEN_STATUSES, GatewayOutcome, PaymentRequest, PaymentStore, SimulatedGateway
from search import DataLayer

REFERENCE_DATE: date = date(2025, 2, 25)
MAX_STEPS: int = 8
RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)

SYSTEM_PROMPT: str = """You help a telecom customer pay an overdue bill. Each turn starts with no memory of earlier turns, so use the tools to find the current state.

Rules:
- State only facts returned by the tools. Do not use general knowledge.
- Quote bill and request IDs in your answer.
- Give no subjective advice.
- If the question does not say whose account it is, ask for a customer ID.
- Each message lists the customer's payment requests with their IDs and status. Use those IDs. Never invent an ID.
- Send a payment request only for the bill the customer names, and only if get_overdue_bills lists that bill. If it is not listed, say it is not overdue and send nothing.
- Only one bill can be awaiting payment at a time. If a request is open, offer to resume it.
- The system records the customer's acceptance, not you. If a request is Awaiting Acceptance, ask the customer to accept it.
- Call get_payment_methods and show the cards. Call make_payment only in a turn where the customer names a card by its last four digits. Never choose a card yourself.
- Call make_payment only once per turn. If a payment is declined, ask for another card and do not retry the same card.
- Say a bill is Paid only when make_payment reports it is Paid.
- If the payment service is unavailable, say the request is saved and offer to retry later.
- Cancel a request only when the customer asks to cancel it.
- If a tool says a step cannot be done, do not repeat that call. Call FinalAnswer and explain what the customer must do next.
- After send_payment_request succeeds, call FinalAnswer and ask the customer to accept the request.
- When you have the answer, call FinalAnswer once, with the bill and request IDs the answer uses.
"""


class AgentRequest(BaseModel):
    customer_id: str
    question: str
    accept_request_id: str | None = None


class FinalAnswer(BaseModel):
    """Give the final answer to the customer. Call this once, with the bill and request IDs the answer uses."""

    reasoning: str = Field(description="One or two sentences on the tool results behind your answer.")
    answer: str
    bill_ids: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    reasoning: str = ""
    answer: str
    outcome: Literal["answered", "unavailable", "step_limit"]
    bill_ids: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)


def bills_with_status(db: Database, store: PaymentStore, customer_id: str) -> list[Bill]:
    """The customer's bills, with any status override from the payment store applied."""
    bills: list[Bill] = DataLayer.get_customer_bills(db, customer_id).bills
    return [b.model_copy(update={"status": store.bill_override(b.bill_id) or b.status}) for b in bills]


def requests_json(store: PaymentStore, customer_id: str) -> str:
    return json.dumps([r.model_dump() for r in store.list_requests(customer_id)])


def accept_request(store: PaymentStore, request_id: str) -> None:
    """Record the customer's acceptance. Only a request awaiting acceptance can be accepted."""
    request: PaymentRequest | None = store.get_request(request_id)
    if request is not None and request.status == "Awaiting Acceptance":
        request.status = "Accepted"
        store.save(request)


def usable_last_4s(db: Database, customer_id: str) -> list[str]:
    methods: list[PaymentMethod] = DataLayer.get_usable_payment_methods(db, customer_id, REFERENCE_DATE).customers[0].payment_methods
    return [m.account_number_last_4 for m in methods]


def charge_with_retries(gateway: SimulatedGateway, idempotency_key: str) -> GatewayOutcome:
    """Charge once. If the gateway is unavailable, retry with backoff. The same key is reused, so a retry cannot double charge."""
    outcome: GatewayOutcome = gateway.charge(idempotency_key)
    for delay in RETRY_DELAYS:
        if outcome != "unavailable":
            break
        time.sleep(delay)
        outcome = gateway.charge(idempotency_key)
    return outcome


def build_tools(db: Database, store: PaymentStore, gateway: SimulatedGateway) -> list[BaseTool]:
    @tool
    def get_overdue_bills(customer_id: str) -> str:
        """List a customer's overdue bills with their amounts and due dates."""
        bills: list[Bill] = [b for b in bills_with_status(db, store, customer_id) if b.status == "Overdue"]
        return Database(plans=[], devices=[], lines=[], customers=[], bills=bills).model_dump_json()

    @tool
    def send_payment_request(customer_id: str, bill_id: str) -> str:
        """Send a payment request for one overdue bill. The bill becomes Awaiting Payment. The customer must accept the request before any charge."""
        bill: Bill | None = next((b for b in bills_with_status(db, store, customer_id) if b.bill_id == bill_id), None)
        if bill is None or bill.status != "Overdue":
            return f"Bill {bill_id} is not an overdue bill for this customer. No request was sent."
        if any(r.status in OPEN_STATUSES for r in store.list_requests(customer_id)):
            return "This customer already has an open payment request. Only one bill can be awaiting payment at a time."
        request: PaymentRequest = store.create_request(customer_id, bill_id, bill.total_due)
        store.set_bill_status(bill_id, "Awaiting Payment")
        return request.model_dump_json()

    @tool
    def check_payment_requests(customer_id: str) -> str:
        """List a customer's payment requests, open and closed, with their IDs and status."""
        return requests_json(store, customer_id)

    @tool
    def get_payment_methods(customer_id: str) -> str:
        """List a customer's payment methods that have not expired. Only these can be used to pay."""
        return DataLayer.get_usable_payment_methods(db, customer_id, REFERENCE_DATE).model_dump_json()

    @tool
    def make_payment(request_id: str, method_last_4: str) -> str:
        """Charge an accepted payment request to a usable card, given by its last four digits. Reports Paid only after the bill reads back as Paid."""
        request: PaymentRequest | None = store.get_request(request_id)
        if request is None or request.status != "Accepted":
            return f"Request {request_id} is not accepted yet. The customer must accept it before any charge."
        if method_last_4 not in usable_last_4s(db, request.customer_id):
            return f"Card ending {method_last_4} is not a usable payment method for this customer. Call get_payment_methods."
        request.method_last_4 = method_last_4
        key: str = f"{request.request_id}:{request.attempt}"
        outcome: GatewayOutcome = charge_with_retries(gateway, key)
        if outcome == "unavailable":
            store.save(request)
            return "The payment service is unavailable. The request is saved as Accepted. Offer to retry later."
        if outcome == "declined":
            request.method_last_4 = None
            request.attempt += 1
            store.save(request)
            return "The payment was declined. Ask the customer for another payment method."
        request.status = "Paid"
        store.save(request)
        store.set_bill_status(request.bill_id, "Paid")
        if store.bill_override(request.bill_id) != "Paid":
            return f"Payment {key} was taken, but bill {request.bill_id} did not read back as Paid. Escalate."
        return f"Payment {key} succeeded. Bill {request.bill_id} is now Paid."

    @tool
    def cancel_payment_request(request_id: str) -> str:
        """Cancel an open payment request. The bill returns to Overdue."""
        request: PaymentRequest | None = store.get_request(request_id)
        if request is None or request.status not in OPEN_STATUSES:
            return f"Request {request_id} is not open, so it cannot be cancelled."
        request.status = "Cancelled"
        store.save(request)
        store.set_bill_status(request.bill_id, "Overdue")
        return request.model_dump_json()

    tools: list[BaseTool] = [
        get_overdue_bills,
        send_payment_request,
        check_payment_requests,
        get_payment_methods,
        make_payment,
        cancel_payment_request,
    ]
    for t in tools:
        t.handle_validation_error = True
    return tools


class Agent:
    """Helps a customer pay an overdue bill. Payment state lives in the store, so each turn starts from the stored requests."""

    def __init__(self, db: Database, llm: BaseChatModel, store: PaymentStore, gateway: SimulatedGateway) -> None:
        self._store: PaymentStore = store
        self._tools_by_name: dict[str, BaseTool] = {t.name: t for t in build_tools(db, store, gateway)}
        self._model: Runnable[LanguageModelInput, AIMessage] = llm.bind_tools(
            [FinalAnswer, *self._tools_by_name.values()], tool_choice="required"
        )

    async def answer(self, request: AgentRequest) -> AgentResponse:
        if request.accept_request_id is not None:
            accept_request(self._store, request.accept_request_id)
        turn_text: str = f"Customer ID: {request.customer_id}\nPayment requests: {requests_json(self._store, request.customer_id)}\n\n{request.question}"
        messages: list[BaseMessage] = [SystemMessage(SYSTEM_PROMPT), HumanMessage(turn_text)]
        try:
            for _ in range(MAX_STEPS):
                reply: AIMessage = await self._model.ainvoke(messages)
                messages.append(reply)
                for call in reply.tool_calls:
                    if call["name"] == FinalAnswer.__name__:
                        final: FinalAnswer = FinalAnswer.model_validate(call["args"])
                        return AgentResponse(outcome="answered", **final.model_dump())
                    result: ToolMessage = self._tools_by_name[call["name"]].invoke(call)
                    messages.append(result)
        except APIConnectionError:
            return AgentResponse(answer=RETRY_MESSAGE, outcome="unavailable")
        return AgentResponse(answer=STEP_LIMIT_MESSAGE, outcome="step_limit")
