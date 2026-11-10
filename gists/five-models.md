# Five Bedrock models, one database

The same requests and the same database rules, 5 models. Four of them saved all 6 configurations. The 4 models that saved all 6 configurations saved identical rows.

Setup: [agent-tool-errors](https://github.com/ggiallo28/agent-tool-errors) at commit [`cae0db72efa810c3d18597501cf258898e7b5a51`](https://github.com/ggiallo28/agent-tool-errors/commit/cae0db72efa810c3d18597501cf258898e7b5a51), Strands Agents, Amazon Bedrock in `us-east-1`, local PostgreSQL 16 in Docker, 2026-11-10. The installation is fictional.

The agent receives only this input:

```text
Installation: install-07
Requests:
R1: Write latency of the media volume
R2: How long files wait before encoding
R3: API response time
R4: API errors
R5: Failed class creations
R6: Depth of the job queue
```

and this system prompt:

```text
Configure one signal per request with propose_config. If a call is rejected, use the valid values in the rejection and call the tool again. Stop only when every request is saved.
```

## Results

| Model | Saved | Tool calls | Rejections | Tokens in / out | Cost | Escalated |
|---|---|---|---|---|---|---|
| Claude Sonnet 4.6 | 6 of 6 | 35 | 29 | 36,403 / 6,459 | $0.2061 | no |
| Claude Haiku 4.5 | 6 of 6 | 33 | 27 | 44,904 / 6,148 | $0.0756 | no |
| Amazon Nova 2 Lite | 6 of 6 | 20 | 14 | 58,905 / 2,300 | $0.0258 | no |
| Amazon Nova Micro | 6 of 6 | 19 | 13 | 51,844 / 2,454 | $0.0022 | no |
| Ministral 3 3B | 0 of 6 | 28 | 25 | 15,477 / 2,759 | $0.0018 | yes |

US cross-region inference profiles can be billed slightly higher than the list price.

## Rows kept

### Claude Sonnet 4.6

| Request | Service | Field | Type | Unit | Sampling (s) |
|---|---|---|---|---|---|
| R1 | media | mst_wr_lat | latency | ms | 10 |
| R2 | encoding | enc_q_wait | latency | s | 10 |
| R3 | api | api_p95 | latency | s | 10 |
| R4 | api | api_5xx | count | count | 10 |
| R5 | classes | cls_create_fail | count | count | 60 |
| R6 | queue | jq_depth | count | count | 10 |

### Claude Haiku 4.5

| Request | Service | Field | Type | Unit | Sampling (s) |
|---|---|---|---|---|---|
| R1 | media | mst_wr_lat | latency | ms | 10 |
| R2 | encoding | enc_q_wait | latency | s | 10 |
| R3 | api | api_p95 | latency | s | 10 |
| R4 | api | api_5xx | count | count | 10 |
| R5 | classes | cls_create_fail | count | count | 60 |
| R6 | queue | jq_depth | count | count | 10 |

### Amazon Nova 2 Lite

| Request | Service | Field | Type | Unit | Sampling (s) |
|---|---|---|---|---|---|
| R1 | media | mst_wr_lat | latency | ms | 10 |
| R2 | encoding | enc_q_wait | latency | s | 10 |
| R3 | api | api_p95 | latency | s | 10 |
| R4 | api | api_5xx | count | count | 10 |
| R5 | classes | cls_create_fail | count | count | 60 |
| R6 | queue | jq_depth | count | count | 10 |

### Amazon Nova Micro

| Request | Service | Field | Type | Unit | Sampling (s) |
|---|---|---|---|---|---|
| R1 | media | mst_wr_lat | latency | ms | 10 |
| R2 | encoding | enc_q_wait | latency | s | 10 |
| R3 | api | api_p95 | latency | s | 10 |
| R4 | api | api_5xx | count | count | 10 |
| R5 | classes | cls_create_fail | count | count | 60 |
| R6 | queue | jq_depth | count | count | 10 |

### Ministral 3 3B

No rows kept.

The 4 models that saved all 6 configurations saved identical rows.

Companion to the article *Predictability, not eloquence* on AWS Builder Center.
