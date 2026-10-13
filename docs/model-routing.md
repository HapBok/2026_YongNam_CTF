# Model profiles

| Stage | Model | Effort | Timeout | Session |
|---|---|---|---|---|
| Intake | gpt-6-luna | medium | 300s | fresh |
| Quick | gpt-6-luna | high | 720s | resumable |
| Triage | gpt-6.1-sol | medium | 480s | fresh |
| General | gpt-6.1-sol | high | 1500s | resumable |
| Security | gpt-6-sol + daybreak_blue | high | 1500s | resumable |
| Rescue | gpt-6-astra | high | 900s | fresh |
| Verify general | gpt-6.1-sol | high | 600s | fresh |
| Verify security | gpt-6-sol + daybreak_blue | high | 600s | fresh |

Luna failure → Sol; Sol failure → GPT-6 Sol High; Astra failure → GPT-6.1 Sol xhigh. Security access failures stop instead of fallback. 404/model-not-found falls back immediately. Transient/timeout retries once after 5s. 429 retries once only when Retry-After <=60s; otherwise QUOTA_WAIT.

Every command uses explicit model, effort, service_tier=default, cyber-access-program=standard or daybreak_blue, workspace-write sandbox, no nested agents, and output schema. CLI options are validated against the pinned 0.162.1 package. GPT-6.1 Sol High/Standard/Daybreak Off is the implementation setting; actual Solver profiles use the table above.

Sources: https://learn.chatgpt.com/docs/developer-commands ; https://learn.chatgpt.com/docs/models ; https://developers.openai.com/api/docs/guides/daybreak ; https://learn.chatgpt.com/docs/agent-configuration/speed

