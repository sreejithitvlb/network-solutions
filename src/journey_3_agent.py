import json
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from models import Bill, BillStatus, Database
from payments import OPEN, PAID, GatewayOutcome, PaymentRequest, PaymentStore, SimulatedGateway
from search import DataLayer

OVERDUE: BillStatus = "Overdue"

SYSTEM_PROMPT: str = """You help a telecom customer pay an overdue bill. Each turn starts with no memory of earlier turns, so use the tools to find the current state.

Rules:
- State only facts returned by the tools. Do not use general knowledge.
- Quote bill and request IDs in your answer.
- If the question does not say whose account it is, ask for a customer ID.
- To pay a bill, call pay_bill with the bill ID. Pay only the bill the customer names.
- If a customer returns, call check_payment_requests first and offer to resume any open request.
- Say a bill is Paid only when pay_bill reports it is Paid.
- If the payment service is unavailable, say the request is saved and offer to retry later.
- If a payment is declined, say so and ask the customer whether to try again.
"""


def overdue_bills(db: Database, store: PaymentStore, customer_id: str) -> list[Bill]:
    """The customer's overdue bills. A bill with a paid request is no longer overdue, even though the bill data still says Overdue."""
    paid: set[str] = {r.bill_id for r in store.list_requests(customer_id) if r.status == PAID}
    return [b for b in DataLayer.get_customer_bills(db, customer_id, OVERDUE).bills if b.bill_id not in paid]


def build_tools(db: Database, store: PaymentStore, gateway: SimulatedGateway) -> list[BaseTool]:
    @tool
    def get_overdue_bills(customer_id: str) -> str:
        """List a customer's overdue bills with amounts and due dates. Bills already paid are left out."""
        bills: list[Bill] = overdue_bills(db, store, customer_id)
        return Database(plans=[], devices=[], lines=[], customers=[], bills=bills).model_dump_json()

    @tool
    def check_payment_requests(customer_id: str) -> str:
        """List a customer's payment requests with their IDs and status. Use this to find unfinished requests."""
        return json.dumps([r.model_dump() for r in store.list_requests(customer_id)])

    @tool
    def pay_bill(customer_id: str, bill_id: str) -> str:
        """Pay an overdue bill. Resumes the bill's open request if there is one, otherwise creates a request, then charges it."""
        bill: Bill | None = next((b for b in overdue_bills(db, store, customer_id) if b.bill_id == bill_id), None)
        if bill is None:
            return f"Bill {bill_id} is not an overdue bill for this customer."
        request: PaymentRequest | None = next(
            (r for r in store.list_requests(customer_id) if r.bill_id == bill_id and r.status == OPEN), None
        )
        if request is None:
            request = store.create_request(customer_id, bill_id, bill.total_due)
        outcome: GatewayOutcome = gateway.charge()
        if outcome == "unavailable":
            return f"The payment service is unavailable. Request {request.request_id} is saved as open."
        if outcome == "declined":
            return f"The payment was declined. Request {request.request_id} is still open."
        request.status = PAID
        store.save(request)
        return f"Bill {bill_id} is now Paid. Payment request {request.request_id}."

    return [get_overdue_bills, check_payment_requests, pay_bill]


class Agent:
    """Helps a customer pay an overdue bill. Each pay_bill call waits for an approval decision. Conversation state is in the checkpointer; payment requests are in the store."""

    def __init__(
        self,
        db: Database,
        llm: BaseChatModel,
        store: PaymentStore,
        gateway: SimulatedGateway,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        self._agent = create_agent(
            model=llm,
            tools=build_tools(db, store, gateway),
            system_prompt=SYSTEM_PROMPT,
            middleware=[HumanInTheLoopMiddleware(interrupt_on={"pay_bill": True})],
            checkpointer=checkpointer,
        )

    def send(self, thread_id: str, text: str) -> dict[str, Any]:
        config: dict[str, dict[str, str]] = {"configurable": {"thread_id": thread_id}}
        return self._agent.invoke({"messages": [("user", text)]}, config)

    def decide(self, thread_id: str, approve: bool) -> dict[str, Any]:
        config: dict[str, dict[str, str]] = {"configurable": {"thread_id": thread_id}}
        decision: dict[str, str] = {"type": "approve"} if approve else {"type": "reject"}
        return self._agent.invoke(Command(resume={"decisions": [decision]}), config)
