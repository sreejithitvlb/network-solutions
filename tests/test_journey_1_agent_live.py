import asyncio
import os
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

import journey_1_agent
from journey_1_agent import Agent, AgentRequest, AgentResponse
from file_loader import load_database
from models import Database
from icecream import ic

DB_PATH: Path = Path(__file__).parents[1] / "datasource" / "db.toml"


@pytest.fixture(scope="module")
def db() -> Database:
    return load_database(DB_PATH)


@pytest.fixture
def support_agent(db: Database) -> Agent:
    llm = ChatOpenAI(
        model=journey_1_agent.MODEL_NAME,
        base_url=journey_1_agent.MODEL_BASE_URL,
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
        timeout=httpx.Timeout(60.0),
    )
    return Agent(db, llm)


def test_what_c1002_owes(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="What does customer C1002 owe?")))
    print(response.answer)
    print(response.reasoning)
    assert "B1005" in response.bill_ids
    assert "425" in response.answer


def test_c1002_lines_and_data_use(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(
        support_agent.answer(AgentRequest(question="What lines and data use does customer C1002 have?"))
    )
    assert "L1004" in response.answer
    assert "L1008" in response.answer


def test_unknown_customer_is_not_found(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="What does customer C9999 owe?")))
    assert response.outcome == "not_found"


def test_customer_found_by_name(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="What is the customer ID for Sarah Johnson?")))
    assert "C1002" in response.answer


def test_customer_found_by_phone(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="Whose account is phone number 555-123-1003?")))
    assert "B1006" in response.bill_ids


def test_bill_lookup_by_id(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="Show me bill B1004.")))
    assert "B1004" in response.answer
    assert "paid" in response.answer.lower()
    assert "425" in response.answer


def test_line_plan_lookup(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="Which plan is line L1003 on?")))
    assert "Basic Plan" in response.answer
    assert "L1003" in response.line_ids


def test_customer_without_lines(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="What lines does customer C1004 have?")))
    assert response.outcome == "answered"
    assert response.line_ids == []

def test_custom_questions(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="How much does customer Michael Lee has paid so far? and how much does he owe us?")))
    ic(response)