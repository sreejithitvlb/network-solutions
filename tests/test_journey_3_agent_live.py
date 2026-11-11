import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

import journey_1_agent
from journey_3_agent import Agent
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


@pytest.fixture
def checkpointer(tmp_path: Path) -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(tmp_path / "checkpoints.sqlite3", check_same_thread=False))


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=journey_1_agent.MODEL_NAME,
        base_url=journey_1_agent.MODEL_BASE_URL,
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
        timeout=httpx.Timeout(60.0),
    )


def run_turn(agent: Agent, thread_id: str, question: str, approve: bool = True) -> None:
    """Send one message. If the agent asks to pay, answer the approval request with the given decision."""
    result: dict[str, Any] = agent.send(thread_id, f"Customer ID: C1002\n\n{question}")
    if "__interrupt__" in result:
        result = agent.decide(thread_id, approve)
    print(result["messages"][-1].content)


def test_pay_overdue_bill_end_to_end(db: Database, store: PaymentStore, checkpointer: SqliteSaver) -> None:
    agent = Agent(db, make_llm(), store, SimulatedGateway([]), checkpointer)
    run_turn(agent, "t1", "Pay overdue bill B1005.")
    requests = store.list_requests("C1002")
    assert len(requests) == 1
    assert requests[0].bill_id == "B1005"
    assert requests[0].status == "Paid"


def test_rejected_approval_does_not_charge(db: Database, store: PaymentStore, checkpointer: SqliteSaver) -> None:
    agent = Agent(db, make_llm(), store, SimulatedGateway([]), checkpointer)
    run_turn(agent, "t1", "Pay overdue bill B1005.", approve=False)
    assert all(r.status != "Paid" for r in store.list_requests("C1002"))


def test_outage_keeps_request_and_resumes_in_new_conversation(
    db: Database, store: PaymentStore, checkpointer: SqliteSaver
) -> None:
    gateway = SimulatedGateway(["unavailable"])
    run_turn(Agent(db, make_llm(), store, gateway, checkpointer), "t1", "Pay overdue bill B1005.")
    requests = store.list_requests("C1002")
    assert len(requests) == 1
    assert requests[0].status == "Open"

    run_turn(Agent(db, make_llm(), store, gateway, checkpointer), "t2", "I am back. Resume the unfinished payment for bill B1005.")
    requests = store.list_requests("C1002")
    assert len(requests) == 1
    assert requests[0].status == "Paid"


def test_declined_payment_can_be_retried(db: Database, store: PaymentStore, checkpointer: SqliteSaver) -> None:
    gateway = SimulatedGateway(["declined"])
    run_turn(Agent(db, make_llm(), store, gateway, checkpointer), "t1", "Pay overdue bill B1005.")
    assert store.list_requests("C1002")[0].status == "Open"

    run_turn(Agent(db, make_llm(), store, gateway, checkpointer), "t2", "Try the payment for bill B1005 again.")
    requests = store.list_requests("C1002")
    assert len(requests) == 1
    assert requests[0].status == "Paid"
