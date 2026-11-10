# Product

This repository accompanies a technical article about agents that write configuration rows, where the rules live in the database instead of the prompt.

## What it does

- An agent proposes one collection configuration per operations request.
- PostgreSQL enforces every rule with named constraints, foreign keys, triggers, column-level grants and roles.
- The tool layer turns each rejection into a one-line instruction. The instruction names the parameter to change and lists up to 10 valid values.

## Agent contract

- The agent receives only the installation id and the requests in plain language.
- Services, fields, units and sampling come back in the rejections.
- The system prompt describes behaviour only, never domain facts.
- The agent can only insert drafts. Only the approver role approves.
- After the same rule rejects the same request 3 times, the run stops and a person takes over.

## Data

- The installation in `manuals/` is fictional.
- No client, sector or person names anywhere.

## Audience

Builders with an AWS account. Everything must be runnable, verifiable and removable.
