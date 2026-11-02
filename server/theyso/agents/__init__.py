from theyso.agents.base import AgentAdapter, AgentContext


def build_adapter(agent: str, ctx: AgentContext) -> AgentAdapter:
    if agent == "claude-code":
        from theyso.agents.claude_code import ClaudeCodeAdapter

        return ClaudeCodeAdapter(ctx)
    if agent == "opencode":
        from theyso.agents.opencode import OpenCodeAdapter

        return OpenCodeAdapter(ctx)
    raise ValueError(f"Unknown agent: {agent}")


__all__ = ["AgentAdapter", "AgentContext", "build_adapter"]
