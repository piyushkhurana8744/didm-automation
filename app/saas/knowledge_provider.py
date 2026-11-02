"""Provider-neutral knowledge release boundary.

Initial implementation is deliberately zero-touch: no class in this module imports an HTTP/MCP client and
no startup job calls it. A future live adapter needs a separate security review and explicit enablement.
"""
from dataclasses import dataclass


class KnowledgeProviderDisabled(Exception):
    pass


@dataclass(frozen=True)
class PreparedRelease:
    agent_version_id: str
    knowledge_snapshot_id: str
    manifest_hash: str


class DisabledKnowledgeProvider:
    name = "disabled"

    def synchronize(self, release: PreparedRelease):
        raise KnowledgeProviderDisabled("Knowledge provider synchronization is disabled.")


def build_knowledge_provider(settings):
    """Fail closed even if the flag is accidentally enabled: no live adapter ships in this phase."""
    if settings.knowledge_sarvam_sync_enabled:
        raise KnowledgeProviderDisabled(
            "KNOWLEDGE_SARVAM_SYNC_ENABLED cannot be enabled: no approved live adapter is installed."
        )
    return DisabledKnowledgeProvider()
