# Journey 3: Overdue bill payment (simulated)

## Goal
Help a customer pay an overdue bill through a simulated payment flow, from request to a bill that is verified as Paid. The starting case is customer C1002 with overdue bill B1005 ($425.00, due 2025-02-26).

## Policy rules (enforced in code, not only in the prompt)
- Check that the bill status is Overdue before sending a payment request.
- Only one bill may be Awaiting Payment per customer at a time.
- Sending a request moves the bill to Awaiting Payment.
- Charge only after the customer accepts the request and chooses a usable payment method.
- Report the bill as Paid only after reading its status back as Paid.
- Only offer payment methods that have not expired on the reference date (2025-02-25).

## Data
- Bills and payment methods come from the journey 1 data (`db.json`, loaded once).
- Mutable state lives in a small SQLite database: payment requests (ID, customer, bill, amount, status, chosen method, attempt number) and bill status overrides.
- Saving state in SQLite means an unfinished request survives a restart and can be resumed in a later conversation.

## Tools
The LLM calls these tools. The code checks every rule above before acting.
- `get_overdue_bills(customer_id)`: lists overdue bills with amounts and due dates.
- `send_payment_request(customer_id, bill_id)`: checks overdue status and the one-open-request rule, then creates the request and sets the bill to Awaiting Payment.
- `check_payment_requests(customer_id)`: shows open and recent requests. Used to resume.
- `accept_payment_request(request_id)`: records the customer's acceptance.
- `get_payment_methods(customer_id)`: lists usable methods only, with last four digits and expiry.
- `make_payment(request_id, method_last_4)`: charges the simulated gateway, then reads the bill back and confirms Paid before returning success.
- `cancel_payment_request(request_id)`: closes the request and returns the bill to Overdue. This is my assumption, because the policy does not cover cancellation.

## Simulated gateway
- A scripted gateway. Each charge consumes the next scripted outcome: `ok`, `declined`, or `unavailable`. When the script runs out, charges succeed.
- Each charge attempt uses an idempotency key (`request_id:attempt_no`). Retries of the same attempt reuse the key, so a lost response cannot cause a double charge.
- Unavailable: retry up to 3 times with backoff. If it still fails, keep the request accepted and tell the customer it is saved.
- Declined: clear the chosen method, increase the attempt number, and ask for another method. The bill stays Awaiting Payment.

## Flow
1. Customer asks to pay. The agent lists overdue bills, sends a request for the chosen bill, and says the request is pending.
2. Customer asks to see requests (`check_payment_requests`) and accepts.
3. Agent lists usable methods and the customer chooses one.
4. `make_payment` runs. Outcomes:
   - Paid: confirm the bill is Paid, with the payment reference.
   - Declined: ask for another method.
   - Gateway unavailable: say the request is saved and offer to retry later.
5. In a later conversation, the agent calls `check_payment_requests` first and offers to resume any open request.

## Agent
- Tool-use loop on the Qwen model, with the policy rules in the system prompt for explanation only. The code enforces the rules.
- The agent states only results returned by tools. It never says a bill is paid until `make_payment` has read back Paid.

## Framework
- The state lives in SQLite, so resuming does not need a graph checkpoint. A plain tool loop is enough.
- LangGraph would make the accept-then-pay pause explicit, and it is an option if you want it.

## Limitations (for the design note)
- There is no verification, as in journey 1, so anyone with a customer ID can start a payment. This is a real risk for payments. A production version would require a second factor before any payment action.
- The gateway is simulated. No real money moves.
- Cancellation is my assumption, not a policy rule.

## Open items
- Verification for payments: keep the journey 1 decision (none), or require a date of birth before any payment action. I recommend the date-of-birth check for this journey, because it moves money.
- Framework: plain tool loop (suggested) or LangGraph.
- Context size: the payment conversation is short, so the 4,096-token limit should not be a problem here.

## Verification plan
- Tests for each rule: overdue check, one-open-request rule, expired card excluded, no charge before acceptance, Paid verified after charge.
- Gateway tests: outage with retry and no double charge, decline with a new attempt key, resume after a restart.
- Live run on the Qwen model: C1002 pays B1005 end to end with the scripted gateway, then a new conversation resumes an outage case.
