# Course platform, installation 07: signal reference

Fictional installation used by the article and the experiment. Any resemblance to a real system is accidental.

This installation runs five services. Each service exposes its counters and gauges on a stats endpoint, described in the OpenAPI schema `course-platform-install-07.openapi.yaml`: the tags are the services, and every property of a stats object is a field that can be collected, with its unit (`x-unit`) and supported sampling (`x-sampling-min-s`, `x-sampling-max-s`). Collect only those fields, because other names are not exposed and will not be ingested.

## Signal types

Every configured signal has one type. The type decides which units are allowed.

| Type | Allowed units |
|---|---|
| latency | ms, s |
| ratio | percent |
| count | count |
| age | s |

## Requests from operations

Configure one signal for each request. The sampling column is what operations asked for: as fine as the source supports, except class creations, which change slowly.

| Request id | Service id | Signal type | Sampling | Request |
|---|---|---|---|---|
| `R1` | `media` | latency | 10 s | Write latency of the media volume |
| `R2` | `encoding` | latency | 10 s | How long files wait before encoding |
| `R3` | `api` | latency | 10 s | API response time |
| `R4` | `api` | count | 10 s | API errors |
| `R5` | `classes` | count | 60 s | Failed class creations |
| `R6` | `queue` | count | 10 s | Depth of the job queue |
