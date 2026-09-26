## Consequences

### Positive

- one primary durable data platform for v1
- easier source/recommendation/evaluation joins
- strong auditability and institutional memory
- fewer infrastructure components
- straightforward integration with existing governed onboarding

### Negative / accepted tradeoffs

- Snowflake is not a conventional OLTP application database
- very interactive review workflows may eventually expose latency/transactional limitations
- careful repository design is required to keep SQL out of graph nodes
- service-role boundary must be reconciled with the simplified Atlas role model

## References

- data#80 Dataset Discovery Agent epic
- data#448 standalone repository boundary
- data#449 Snowflake schema / least-privilege contract
- data#450 governed handoff
- data#451 this ADR story
- data#85 application persistence
- data#87 DigitalOcean deployment
