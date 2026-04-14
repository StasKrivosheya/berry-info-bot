# Trace Log Keys

Canonical structured log keys for the tracing baseline:

- `timestamp`: UTC ISO-8601 timestamp emitted by the JSON formatter
- `level`: log level
- `logger`: Python logger name
- `message`: original log message
- `event`: canonical trace event name
- `trace_id`: correlation identifier for a bot update or traced pipeline execution
- `stage`: pipeline stage name for span events
- `status`: span or request outcome
- `start_ms`: span start timestamp in epoch milliseconds
- `end_ms`: span end timestamp in epoch milliseconds
- `duration_ms`: elapsed span duration in milliseconds
- `meta`: structured stage or request metadata

Canonical event names:

- `trace_request_started`
- `trace_request_finished`
- `trace_span`

Example request-start log line:

```json
{"timestamp":"2026-04-14T11:20:33.184000+00:00","level":"INFO","logger":"app.bot.middlewares.tracing","message":"trace_request_started","event":"trace_request_started","trace_id":"9dfd3f76-10e4-4b0f-9344-8c1eb3fd0f9b","source":"telegram_update","request_id_source":"generated","meta":{"event_type":"Update"}}
```

Example stage-span log line:

```json
{"timestamp":"2026-04-14T11:20:33.201000+00:00","level":"INFO","logger":"app.observability.logger","message":"trace_span","event":"trace_span","trace_id":"9dfd3f76-10e4-4b0f-9344-8c1eb3fd0f9b","stage":"retrieval","start_ms":1776165633188,"end_ms":1776165633201,"duration_ms":13,"status":"ok","meta":{"strategy":"detail_retrieval","phase":"primary","retrieval_source":"rules"}}
```
