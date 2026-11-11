import asyncio
import os
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

import journey_1_agent
from journey_2_agent import Agent, AgentRequest, AgentResponse
from file_loader import load_database
from models import Database

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


def test_no_signal_cites_cellular_sections(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="My phone has no signal.")))
    print(response.answer)
    assert any("Cellular Service" in c for c in response.citations)


def test_pictures_cite_mms_sections(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="Pictures won't send.")))
    print(response.answer)
    assert any("MMS" in c for c in response.citations)


def test_slow_internet_cites_mobile_data_sections(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="My internet is slow.")))
    print(response.answer)
    assert any("Mobile Data" in c for c in response.citations)


def test_question_outside_manual_is_not_covered(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(support_agent.answer(AgentRequest(question="What is the weather?")))
    print(response.answer)
    assert response.outcome == "not_covered"


def test_number_not_on_account(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(
        support_agent.answer(AgentRequest(question="My phone has no signal.", phone_number="555-999-0000"))
    )
    assert response.outcome == "not_on_account"


def test_suspended_line_is_reported(support_agent: Agent) -> None:
    response: AgentResponse = asyncio.run(
        support_agent.answer(AgentRequest(question="My phone has no signal.", phone_number="555-123-2003"))
    )
    print(response.answer)
    assert "suspend" in response.answer.lower()
