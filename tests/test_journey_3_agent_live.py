import asyncio
import os
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

import journey_1_agent
from journey_3_agent import Agent, AgentRequest, AgentResponse
from file_loader import load_database
from models import Database
from payments import PaymentStore, SimulatedGateway

DB_PATH: Path = Path(__file__).parents[1] / "datasource" / "db.toml"


@pytest.fixture(scope="module")
def db() -> Database:
    return load_database(DB_PATH)


@pytest.fixture
def store(tmp_path: Path) -> PaymentStore:
    return PaymentStore(tmp_path / "payments.sqlite3")


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=journey_1_agent.MODEL_NAME,
        base_url=journey_1_agent.MODEL_BASE_URL,
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
        timeout=httpx.Timeout(60.0),
    )


def ask(
    db: Database,
    store: PaymentStore,
    gateway: SimulatedGateway,
    question: str,
    accept_request_id: str | None = None,
) -> AgentResponse:
    """One conversation turn. Each turn builds its own agent, so the store is the only state carried between turns."""
    agent = Agent(db, make_llm(), store, gateway)
    request = AgentRequest(customer_id="C1002", question=question, accept_request_id=accept_request_id)
    response: AgentResponse = asyncio.run(agent.answer(request))
    print(response.answer)
    print(response.reasoning)
    return response


def test_pay_overdue_bill_end_to_end(db: Database, store: PaymentStore) -> None:
    gateway = SimulatedGateway([])
    ask(db, store, gateway, "Customer C1002 wants to pay an overdue bill.")
    request = store.list_requests("C1002")[0]
    assert request.bill_id == "B1005"
    assert request.status == "Awaiting Acceptance"

    ask(db, store, gateway, "Customer C1002 accepts the payment request.", accept_request_id=request.request_id)
    assert store.get_request(request.request_id).status == "Accepted"

    ask(db, store, gateway, "Customer C1002 chooses the debit card ending 1234. Pay the request.")
    assert store.get_request(request.request_id).status == "Paid"
    assert store.bill_override("B1005") == "Paid"


def test_no_charge_before_acceptance(db: Database, store: PaymentStore) -> None:
    gateway = SimulatedGateway([])
    ask(db, store, gateway, "Customer C1002 wants to pay an overdue bill.")
    request = store.list_requests("C1002")[0]

    ask(db, store, gateway, "Customer C1002 says pay now with the debit card ending 1234.")
    assert store.get_request(request.request_id).status == "Awaiting Acceptance"
    assert store.bill_override("B1005") == "Awaiting Payment"


def test_paid_bill_is_not_sent_as_request(db: Database, store: PaymentStore) -> None:
    ask(db, store, SimulatedGateway([]), "Send a payment request for bill B1004 for customer C1002.")
    assert not any(r.bill_id == "B1004" for r in store.list_requests("C1002"))


def test_outage_keeps_request_and_resumes_later(db: Database, store: PaymentStore) -> None:
    gateway = SimulatedGateway(["unavailable"] * 4)
    ask(db, store, gateway, "Customer C1002 wants to pay an overdue bill.")
    request = store.list_requests("C1002")[0]
    ask(db, store, gateway, "Customer C1002 accepts the payment request.", accept_request_id=request.request_id)
    ask(db, store, gateway, "Customer C1002 chooses the debit card ending 1234. Pay the request.")
    assert store.get_request(request.request_id).status == "Accepted"
    assert store.bill_override("B1005") == "Awaiting Payment"

    ask(db, store, SimulatedGateway([]), "Customer C1002 is back. Resume the open payment request with the debit card ending 1234.")
    assert store.get_request(request.request_id).status == "Paid"


def test_declined_payment_asks_for_new_method(db: Database, store: PaymentStore) -> None:
    gateway = SimulatedGateway(["declined"])
    ask(db, store, gateway, "Customer C1002 wants to pay an overdue bill.")
    request = store.list_requests("C1002")[0]
    ask(db, store, gateway, "Customer C1002 accepts the payment request.", accept_request_id=request.request_id)
    ask(db, store, gateway, "Customer C1002 chooses the debit card ending 1234. Pay the request.")
    assert store.get_request(request.request_id).status == "Accepted"
    assert store.get_request(request.request_id).attempt == 2
    assert store.bill_override("B1005") == "Awaiting Payment"

    ask(db, store, gateway, "Customer C1002 chooses the credit card ending 5678 instead. Pay the request.")
    assert store.get_request(request.request_id).status == "Paid"
