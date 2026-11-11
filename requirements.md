# Network Solutions AI CoE Candidate Assignment

## AI Support Assistant

**Confidential — Internal use only**
**Submission:** Within 48 hours | **Expected effort:** 6–8 hours

## Scenario

Build an AI support assistant for a fictional telecom provider. It should help customers understand their account, troubleshoot service issues, and pay overdue bills.

The provider expects customer volume and support capabilities to grow. Customers may return to unfinished requests in later conversations, and external services may occasionally be unavailable.

## Requirements

Demonstrate three customer journeys:

- Answer an account question using customer, plan, line, or billing data.
- Answer a troubleshooting question using support documentation, with source references.
- Help a customer resolve an overdue bill using a simulated payment flow.

Create a single-agent or multi-agent harness, depending on what you see fit for this use case. Explain your choices in terms of robustness, maintainability, and long-term scalability.

Use the supplied data and documentation to determine appropriate customer support behavior. Decide how your system handles incomplete requests and failures.

Choose your own technology stack and architecture. An API, CLI, or minimal chat interface is sufficient; all payments should be simulated.

## Corpus and seed data

Download these files from the τ-bench telecom corpus.

| File | Contents |
|------|----------|
| db.toml | Customer, plan, line, device, and billing records |
| main_policy.md | Business policies |
| tech_support_manual.md | Troubleshooting knowledge |

Read the seed data directly or import it into your chosen database. The corpus provides the scenario context; you are free to design your own implementation.

For a starting payment case, customer **C1002** has overdue bill **B1005**.

## Submission and review

Submit a repository or zip containing:

- Runnable code and setup instructions.
- A short design note with an architecture diagram, tradeoffs, and limitations.
- Tests or repeatable examples demonstrating the main journeys and important failure cases.

We will focus on your design decisions, working behavior, and handling of realistic edge cases. Be ready to explain how your solution would evolve as usage and requirements grow.

AI coding tools are welcome. Submit code you can explain.
