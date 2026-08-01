# CALYX-AGENT-002 — External AI Provider and Governed Synthesis

## Purpose

Connect the internal Calyx agent to an external language model without transferring governance authority to that model.

## Authority boundary

The Orchid Continuum server remains authoritative for:

- intent classification;
- action class;
- tool selection and execution;
- approval requirements;
- scientific publication controls;
- deterministic evidence and step status.

The external provider receives only a sanitized representation of the user request, deterministic summary, governed steps, and read-only tool results. It receives no database credentials, GitHub credentials, production tools, or function definitions.

The provider may synthesize a readable answer and recommendations. It may not execute work, change an approval decision, or claim completion contrary to the server-owned step records.

## Initial provider

The first adapter uses the OpenAI Responses API and is configured through:

- `CALYX_AGENT_PROVIDER=openai`
- `CALYX_AGENT_MODEL=<approved model>`
- `OPENAI_API_KEY=<secret>`
- optional `CALYX_AGENT_BASE_URL`
- optional `CALYX_AGENT_TIMEOUT_SECONDS`

No provider is called during startup. Requests can disable provider synthesis with `use_provider=false`.

## Failure behavior

Missing configuration produces deterministic planning only. Invalid configuration is reported without exposing secrets. Network, HTTP, JSON, empty-response, and provider failures fail closed to the deterministic Calyx response.

## Provenance

Responses expose provider ID, model, and provider response ID when available. Private chain-of-thought is neither requested nor stored.

## Deferred work

- durable conversational sessions;
- provider allowlists and cost budgets;
- additional provider adapters;
- streaming responses;
- approved tool-call orchestration;
- deployment and secret configuration.
