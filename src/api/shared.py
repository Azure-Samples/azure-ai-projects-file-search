from typing import Dict
from azure.ai.projects.aio import AIProjectClient


from azure.ai.projects.models import (
    Agent,
    VectorStore
)


class ChatBlueprint():
    ai_client: AIProjectClient
    agent: Agent
    files: Dict[str, str]
    vector_store: VectorStore
    
    
bp = ChatBlueprint()

__all__ = ["bp"]