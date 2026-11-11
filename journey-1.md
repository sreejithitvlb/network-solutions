# Journey 1: Account questions

## Goal
Answer account questions (bills, plan, lines, data usage) using the customer, plan, line, and billing data.

## Data
- Load the seed data once into a single JSON object: plans, devices, lines, customers, and bills.
- Build in-memory search indexes at load time (by ID, by phone number, by name, customer to lines, customer to bills).
- Hide storage behind one data layer, so the data can grow or move to a database without changing the agent.

## Search tools
The LLM never sees the whole dataset. It can only answer from what its tools return.

- Find a customer by customer ID, phone number, or name.
- Get a customer's lines, including plan and device.
- Get a customer's bills, optionally filtered by status.
- Look up one bill, one line, or one plan by ID.

## Agent
- An LLM tool-use loop with an iteration cap.
- The agent chooses the tools the question needs, searches, and answers.
- The system prompt says to:
  - state only facts returned by tools
  - quote bill and line IDs in answers
  - give no subjective advice
  - say so when the data does not contain the answer
  - ask for a customer ID, phone number, or name when the question does not say whose account it is

## Failures
- A tool error goes back to the model as a result it can explain.
- If the model API is unavailable, the customer gets a short retry message.

## Limitations (for the design note)
- There is no verification step. Anyone who gives a customer ID can ask about that account. A production version would add verification.

## Open items
- Model name and API key, to be provided by the user.

## Verification plan
- Tests for each search function.
- Agent loop tests with a scripted fake model (no API key needed).
- Live check with the chosen model:
  - Ask what C1002 owes. Expect B1005, Overdue, $425.00.
  - Ask about C1002's lines and data use.
  - Ask about an unknown customer ID and confirm the agent says it cannot find the account.
