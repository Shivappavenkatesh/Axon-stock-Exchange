"""Core capital engine components (regime, risk, kill switch, execution wrappers).

This package provides higher-level orchestration primitives that sit on top of
existing Axon modules (risk, execution, broker, etc.). It intentionally
remains broker-agnostic at the interface level but is currently wired to
Angel One under the hood.
"""
