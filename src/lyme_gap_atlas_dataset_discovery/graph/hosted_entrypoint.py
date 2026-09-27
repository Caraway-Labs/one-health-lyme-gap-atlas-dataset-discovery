"""Managed Harness Runtime export of the real sequential graph."""

from .hosted import HostedConfig, build_hosted_graph

graph = build_hosted_graph(HostedConfig.from_environment())
