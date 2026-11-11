# Journey 2: Troubleshooting with source references

## Goal
Answer a troubleshooting question using the technical support manual, and cite the manual sections the answer came from.

## Source
- `tech_support_manual.md` (about 17.6 KB), from the τ²-bench telecom corpus.
- The manual is the only knowledge source. The agent does not answer from general knowledge.

## Approach (current scope)
- Current scope passes the whole manual to the model in the prompt on every question. The embedding service above is available for the retrieval step when it is added.
- The model answers from that text and cites the heading path of each section it uses. The heading paths are already in the manual, so the agent only needs to quote them.
- Semantic search can be added later without changing the answer format. It would replace the full-document prompt with retrieved sections.

## Embedding service (verified)
- Endpoint: `http://100.66.165.94:8001/v1` (OpenAI-compatible, served by vLLM).
- Model name to send: `e5-small` (base model `intfloat/e5-small`).
- Output: 384-dimensional vectors. The endpoint returned HTTP 200 on `/v1/embeddings` and `/v1/models` lists `e5-small` only.
- Max input length: `max_model_len: 512` tokens. Each chunk of the manual must fit within 512 tokens, so chunking is required before indexing.
- E5 models expect text prefixes: `query: ` for questions and `passage: ` for manual chunks. Apply them in the client code.
- This service is separate from the chat model server at port 8000.

## Context size (must be checked before building)
- The model server at 100.66.165.94:8000 reports `max_model_len: 4096` tokens. That limit covers the system prompt, the manual, the question, and the answer.
- The manual is about 17.6 K characters, which is roughly 4,000 to 5,000 tokens. That alone may not fit in 4,096.
- Options:
  1. Restart the server with a larger `--max-model-len` (for example 8192), if the GPU memory allows it.
  2. Trim the prompt to only the sections the question needs. This is a manual selection by heading, not semantic search.
- Measure the real token count with the model's tokenizer before choosing.

## Agent
- A single model call with the manual in the system prompt. No tools are needed for this journey.
- Answer rules:
  - Use only the manual text. Do not use general knowledge.
  - Cite the heading path for each step given.
  - Phrase steps as things the customer does on their phone. Manual tool names such as `toggle_airplane_mode()` are not customer actions and should not appear as instructions.
  - When a step is an escalation (for example, a SIM locked by PIN or PUK entries), say the case needs technical support.
  - If the manual does not cover the question, say so and offer a transfer to a human agent. Do not guess.
- The agent does not perform device actions. It only guides the customer.

## Line context (uses journey 1 data)
- If the customer gives a phone number, look up the line with the journey 1 line search.
- If the line is suspended, say so and refer to the policy: lines are suspended for an overdue bill or a contract end date in the past.
- If the phone number is not on any account, ask for a number that is on the account instead of troubleshooting an unknown line.
- Journey 2 does not verify the customer, matching journey 1.

## Failures
- Model API unavailable: a short retry message, as in journey 1.
- Prompt too long for the context window: fail with a clear error that names the token count, rather than truncating the manual silently.

## Limitations (for the design note)
- Passing the whole manual every time costs more tokens per question and does not scale to a larger knowledge base. Retrieval is the planned fix for that.
- The answer is only as reliable as the model's reading of the manual. The citations let a reviewer check it.

## Open items
- Context size: raise the server's `--max-model-len`, or trim the prompt by section. Decide after measuring the token count.
- Agent framework: a plain model call is enough for this journey. LangGraph is not needed here.

## Verification plan
- Measure the manual's token count with the model's tokenizer, and confirm it fits the chosen context size with room for the question and answer.
- Live check on the Qwen model with three questions:
  - "my phone has no signal" should cite the cellular service sections.
  - "pictures won't send" should cite the MMS sections.
  - "internet is slow" should cite the mobile data sections.
- Refusal check: "what is the weather" should get "not covered by the manual" and a transfer offer.
