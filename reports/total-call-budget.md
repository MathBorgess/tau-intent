# Explicit total call budget

Use `--max-total-calls 32` to cap requests to the provider in each agent episode.
It replaces the productive turn cap for that episode.
Without this flag, the legacy productive turn cap still applies.

Each POST try consumes one call before the transport sends it.
Failed requests consume calls too.
Final answers, gate replies, `record_intent`, and `recall_intent` share the same budget.
The transport rejects any request beyond the cap.
The supervisor stops at the cap and publishes valid pending intents without another model call.
A valid final answer on call 32 can still finish normally.

With this cap, the SDK cannot retry by itself.
Preflight requests use a separate provider and sit outside the episode budget.
An infrastructure retry starts a new episode.
Use `--infra-retries 0` when the full unit must stay within 32 requests.
Discarded retry receipts include their call counts and cap fields.

Records from bench include `actual_total_calls`, `total_call_cap`, `total_call_count_source`, and `total_call_budget_scope`.
Native records count requests at the transport.
A fake harness has no transport.
Its tests count events for answers.
The budget covers agent calls; rescue calls remain outside this scope.
The counted A/B consultation protocol has no rescue arm.
