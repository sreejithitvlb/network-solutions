import json
from datetime import date
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from models import Bill, BillStatus, Database
from payments import OPEN, PAID, GatewayOutcome, PaymentRequest, PaymentStore, simulated_charge
from search import DataLayer

OVERDUE: BillStatus = "Overdue"
REFERENCE_DATE: date = date(2025, 2, 25)

SYSTEM_PROMPT: str = """You help a telecom customer pay an overdue bill. Each turn starts with no memory of earlier turns, so use the tools to find the current state.

Rules:
- State only facts returned by the tools. Do not use general knowledge.
- Quote bill and request IDs in your answer.
- If the question does not say whose account it is, ask for a customer ID.
- Call get_customer_payment_details first. It lists the customer's usable payment methods, overdue bills and payment requests.
- To pay, call make_payment with the bill ID and the last four digits of the card the customer chose. Never choose a card yourself.
- If a payment request is open, offer to resume it by calling make_payment for its bill.
- Say a bill is Paid only when make_payment reports it is Paid.
- If the payment service is unavailable, say the request is saved and offer to retry later.
- If a payment is declined, say so and ask the customer whether to try again.
"""


def overdue_bills(db: Database, store: PaymentStore, customer_id: str) -> list[Bill]:
    """The customer's overdue bills. A bill with a paid request is no longer overdue, even though the bill data still says Overdue."""
    paid: set[str] = {r.bill_id for r in store.list_requests(customer_id) if r.status == PAID}
    return [b for b in DataLayer.get_customer_bills(db, customer_id, OVERDUE).bills if b.bill_id not in paid]


def build_tools(db: Database, store: PaymentStore, script: list[GatewayOutcome]) -> list[BaseTool]:
    @tool
    def get_customer_payment_details(customer_id: str) -> str:
        """Get a customer's usable payment methods, overdue bills and payment requests."""
        usable: Database = DataLayer.get_usable_payment_methods(db, customer_id, REFERENCE_DATE)
        details: dict[str, Any] = {
            "customers": [c.model_dump() for c in usable.customers],
            "overdue_bills": [b.model_dump() for b in overdue_bills(db, store, customer_id)],
            "payment_requests": [r.model_dump() for r in store.list_requests(customer_id)],
        }
        return json.dumps(details, default=str)

    @tool
    def make_payment(customer_id: str, bill_id: str, card_last_4: str) -> str:
        """Pay an overdue bill with a usable card, given by its last four digits. Resumes the bill's open request if there is one, otherwise creates one, then charges it."""
        bill: Bill | None = next((b for b in overdue_bills(db, store, customer_id) if b.bill_id == bill_id), None)
        if bill is None:
            return f"Bill {bill_id} is not an overdue bill for this customer."
        usable: Database = DataLayer.get_usable_payment_methods(db, customer_id, REFERENCE_DATE)
        if card_last_4 not in [m.account_number_last_4 for m in usable.customers[0].payment_methods]:
            return f"Card ending {card_last_4} is not a usable payment method for this customer."
        request: PaymentRequest | None = next(
            (r for r in store.list_requests(customer_id) if r.bill_id == bill_id and r.status == OPEN), None
        )
        if request is None:
            request = store.create_request(customer_id, bill_id, bill.total_due)
        outcome: GatewayOutcome = simulated_charge(script)
        if outcome == "unavailable":
            return f"The payment service is unavailable. Request {request.request_id} is saved as open."
        if outcome == "declined":
            return f"The payment was declined. Request {request.request_id} is still open."
        request.status = PAID
        store.save(request)
        return f"Bill {bill_id} is now Paid. Payment request {request.request_id}."

    return [get_customer_payment_details, make_payment]


class Agent:
    """Helps a customer pay an overdue bill. Each make_payment call waits for an approval decision. Conversation state is in the checkpointer; payment requests are in the store."""

    def __init__(
        self,
        db: Database,
        llm: BaseChatModel,
        store: PaymentStore,
        script: list[GatewayOutcome],
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        self._agent = create_agent(
            model=llm,
            tools=build_tools(db, store, script),
            system_prompt=SYSTEM_PROMPT,
            middleware=[HumanInTheLoopMiddleware(interrupt_on={"make_payment": True})],
            checkpointer=checkpointer,
        )

    def send(self, thread_id: str, text: str) -> dict[str, Any]:
        config: dict[str, dict[str, str]] = {"configurable": {"thread_id": thread_id}}
        return self._agent.invoke({"messages": [("user", text)]}, config)

    def decide(self, thread_id: str, approve: bool) -> dict[str, Any]:
        config: dict[str, dict[str, str]] = {"configurable": {"thread_id": thread_id}}
        decision: dict[str, str] = {"type": "approve"} if approve else {"type": "reject"}
        return self._agent.invoke(Command(resume={"decisions": [decision]}), config)
