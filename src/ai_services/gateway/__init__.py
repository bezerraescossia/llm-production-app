"""LLM gateway: one interface for every component that needs a model completion."""

from ai_services.gateway.orchestrator import CompletionStream, Gateway

__all__ = ["CompletionStream", "Gateway"]
