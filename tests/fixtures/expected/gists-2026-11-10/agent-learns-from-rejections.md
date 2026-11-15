# Amazon Nova Micro learns a schema from database rejections

Amazon Nova Micro on Amazon Bedrock gets the requests in plain language and no schema. Every field name, unit, service and sampling interval reaches it through PostgreSQL rejections, and it saved all 6 configurations after 13 rejections in 19 tool calls.

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

## Raw trace

One JSON line per tool call, unedited: UTC timestamp, the call, what the agent got back, the raw database message.

```text
{"ts": "2026-11-10T15:42:50.094+00:00", "call": {"request_id": "R1", "service_id": "install-07", "signal_name": "Write latency of the media volume", "signal_type": "latency", "source_field": "media_volume", "unit": "ms", "sample_seconds": "1"}, "result": "REJECTED (signal_name_check). Not saved. signal_name must be lowercase letters, digits and underscores, 3 to 41 characters.", "db_message": "new row for relation \"collection_configs\" violates check constraint \"collection_configs_signal_name_check\"\nDETAIL:  Failing row contains (89, eval-nova-micro-1794325367, install-07, R1, install-07, Write latency of the media volume, latency, media_volume, ms, 1, us.amazon.nova-micro-v1:0, draft, agent_writer, null, f)."}
{"ts": "2026-11-10T15:42:51.039+00:00", "call": {"request_id": "R1", "service_id": "install-07", "signal_name": "write_latency_media_volume", "signal_type": "latency", "source_field": "media_volume", "unit": "ms", "sample_seconds": "1"}, "result": "REJECTED (config_field_exists). Not saved. Unknown source_field. Valid source_field: api_5xx, api_p95, cls_create_fail, enc_active, enc_q_wait, jq_depth, jq_oldest, mst_free_pct, mst_wr_lat.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_field_exists\"\nDETAIL:  Key (installation_id, source_field)=(install-07, media_volume) is not present in table \"source_fields\"."}
{"ts": "2026-11-10T15:42:51.921+00:00", "call": {"request_id": "R1", "service_id": "install-07", "signal_name": "write_latency_media_volume", "signal_type": "latency", "source_field": "mst_wr_lat", "unit": "ms", "sample_seconds": "1"}, "result": "REJECTED (config_sampling_supported). Not saved. sample_seconds not supported by this source_field. Valid range: 10 to 300 seconds.", "db_message": "config_sampling_supported: sample_s 1 outside 10 to 300 for mst_wr_lat\nCONTEXT:  PL/pgSQL function check_sampling() line 16 at RAISE"}
{"ts": "2026-11-10T15:42:52.910+00:00", "call": {"request_id": "R1", "service_id": "install-07", "signal_name": "write_latency_media_volume", "signal_type": "latency", "source_field": "mst_wr_lat", "unit": "ms", "sample_seconds": "30"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: media.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R1, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:42:53.854+00:00", "call": {"request_id": "R1", "service_id": "media", "signal_name": "write_latency_media_volume", "signal_type": "latency", "source_field": "mst_wr_lat", "unit": "ms", "sample_seconds": "30"}, "result": "REJECTED (config_sampling_requested). Not saved. Wrong sample_seconds for this request. Valid sample_seconds: 10.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_sampling_requested\"\nDETAIL:  Key (installation_id, request_id, sample_s)=(install-07, R1, 30) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:42:54.813+00:00", "call": {"request_id": "R1", "service_id": "media", "signal_name": "write_latency_media_volume", "signal_type": "latency", "source_field": "mst_wr_lat", "unit": "ms", "sample_seconds": "10"}, "result": "Saved as draft: write_latency_media_volume <- mst_wr_lat (ms, every 10 s). A person will review it.", "db_message": null}
{"ts": "2026-11-10T15:42:55.748+00:00", "call": {"request_id": "R2", "service_id": "install-07", "signal_name": "file_wait_before_encoding", "signal_type": "latency", "source_field": "enc_q_wait", "unit": "s", "sample_seconds": "10"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: encoding.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R2, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:42:56.801+00:00", "call": {"request_id": "R2", "service_id": "encoding", "signal_name": "file_wait_before_encoding", "signal_type": "latency", "source_field": "enc_q_wait", "unit": "s", "sample_seconds": "10"}, "result": "Saved as draft: file_wait_before_encoding <- enc_q_wait (s, every 10 s). A person will review it.", "db_message": null}
{"ts": "2026-11-10T15:42:57.723+00:00", "call": {"request_id": "R3", "service_id": "install-07", "signal_name": "api_response_time", "signal_type": "latency", "source_field": "api_p95", "unit": "ms", "sample_seconds": "10"}, "result": "REJECTED (config_unit_matches_source). Not saved. Wrong unit for this source_field. Valid unit: s.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_unit_matches_source\"\nDETAIL:  Key (installation_id, source_field, unit)=(install-07, api_p95, ms) is not present in table \"source_fields\"."}
{"ts": "2026-11-10T15:42:58.715+00:00", "call": {"request_id": "R3", "service_id": "install-07", "signal_name": "api_response_time", "signal_type": "latency", "source_field": "api_p95", "unit": "s", "sample_seconds": "10"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: api.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R3, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:42:59.836+00:00", "call": {"request_id": "R3", "service_id": "api", "signal_name": "api_response_time", "signal_type": "latency", "source_field": "api_p95", "unit": "s", "sample_seconds": "10"}, "result": "Saved as draft: api_response_time <- api_p95 (s, every 10 s). A person will review it.", "db_message": null}
{"ts": "2026-11-10T15:43:01.040+00:00", "call": {"request_id": "R4", "service_id": "install-07", "signal_name": "api_errors", "signal_type": "count", "source_field": "api_5xx", "unit": "count", "sample_seconds": "10"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: api.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R4, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:43:02.074+00:00", "call": {"request_id": "R4", "service_id": "api", "signal_name": "api_errors", "signal_type": "count", "source_field": "api_5xx", "unit": "count", "sample_seconds": "10"}, "result": "Saved as draft: api_errors <- api_5xx (count, every 10 s). A person will review it.", "db_message": null}
{"ts": "2026-11-10T15:43:03.081+00:00", "call": {"request_id": "R5", "service_id": "install-07", "signal_name": "failed_class_creations", "signal_type": "count", "source_field": "cls_create_fail", "unit": "count", "sample_seconds": "10"}, "result": "REJECTED (config_sampling_supported). Not saved. sample_seconds not supported by this source_field. Valid range: 30 to 600 seconds.", "db_message": "config_sampling_supported: sample_s 10 outside 30 to 600 for cls_create_fail\nCONTEXT:  PL/pgSQL function check_sampling() line 16 at RAISE"}
{"ts": "2026-11-10T15:43:04.278+00:00", "call": {"request_id": "R5", "service_id": "install-07", "signal_name": "failed_class_creations", "signal_type": "count", "source_field": "cls_create_fail", "unit": "count", "sample_seconds": "30"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: classes.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R5, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:43:05.324+00:00", "call": {"request_id": "R5", "service_id": "classes", "signal_name": "failed_class_creations", "signal_type": "count", "source_field": "cls_create_fail", "unit": "count", "sample_seconds": "30"}, "result": "REJECTED (config_sampling_requested). Not saved. Wrong sample_seconds for this request. Valid sample_seconds: 60.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_sampling_requested\"\nDETAIL:  Key (installation_id, request_id, sample_s)=(install-07, R5, 30) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:43:06.446+00:00", "call": {"request_id": "R5", "service_id": "classes", "signal_name": "failed_class_creations", "signal_type": "count", "source_field": "cls_create_fail", "unit": "count", "sample_seconds": "60"}, "result": "Saved as draft: failed_class_creations <- cls_create_fail (count, every 60 s). A person will review it.", "db_message": null}
{"ts": "2026-11-10T15:43:07.462+00:00", "call": {"request_id": "R6", "service_id": "install-07", "signal_name": "job_queue_depth", "signal_type": "count", "source_field": "jq_depth", "unit": "count", "sample_seconds": "10"}, "result": "REJECTED (config_service_matches_request). Not saved. Wrong service_id for this request. Valid service_id: queue.", "db_message": "insert or update on table \"collection_configs\" violates foreign key constraint \"config_service_matches_request\"\nDETAIL:  Key (installation_id, request_id, service_id)=(install-07, R6, install-07) is not present in table \"signal_requests\"."}
{"ts": "2026-11-10T15:43:08.557+00:00", "call": {"request_id": "R6", "service_id": "queue", "signal_name": "job_queue_depth", "signal_type": "count", "source_field": "jq_depth", "unit": "count", "sample_seconds": "10"}, "result": "Saved as draft: job_queue_depth <- jq_depth (count, every 10 s). A person will review it.", "db_message": null}
run=eval-nova-micro-1794325367 calls=19 follow_ups=1 escalated=None input_tokens=51844 output_tokens=2454
```

## Rows the database kept

| Request | Service | Field | Type | Unit | Sampling (s) |
|---|---|---|---|---|---|
| R1 | media | mst_wr_lat | latency | ms | 10 |
| R2 | encoding | enc_q_wait | latency | s | 10 |
| R3 | api | api_p95 | latency | s | 10 |
| R4 | api | api_5xx | count | count | 10 |
| R5 | classes | cls_create_fail | count | count | 60 |
| R6 | queue | jq_depth | count | count | 10 |

Companion to the article *Predictability, not eloquence* on AWS Builder Center.
