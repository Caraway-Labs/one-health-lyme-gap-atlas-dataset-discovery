# Harness Runtime deployment boundary

This directory will hold the secret-free environment spec in Story #11. The root `langgraph.json` and compiled graph are established in Story #1. No deployment, paid resource, private clone credential, model key, Snowflake credential, or schedule is created by the foundation story. Before manual launch, verify current `doctl harness-runtime` support and pin `FRAMEWORK_REPO_SHA` to the evaluated remote commit.
