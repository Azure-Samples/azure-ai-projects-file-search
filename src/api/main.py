import contextlib
import logging
import os

import fastapi
from azure.ai.projects.aio import AIProjectClient
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles


from typing import AsyncGenerator, Dict, Optional, Tuple


import os
from azure.ai.projects.aio import AIProjectClient
from azure.identity import DefaultAzureCredential

from azure.ai.projects.models import (
    MessageDeltaChunk,
    ThreadMessage,
    FileSearchTool,
    AsyncToolSet,
    FilePurpose,
    ThreadMessage,
    StreamEventData,
    AsyncAgentEventHandler,
    Agent,
    VectorStore
)

from .shared import bp



logger = logging.getLogger("azureaiapp")
logger.setLevel(logging.INFO)


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    


    ai_client = AIProjectClient.from_connection_string(
        credential=DefaultAzureCredential(exclude_shared_token_cache_credential=True),
        conn_str=os.environ["PROJECT_CONNECTION_STRING"],
    )
    
    # TODO: add more files are not supported for citation at the moment
    file_names = ["product_info_1.md", "product_info_2.md"]
    files: Dict[str, str] = {}
    for file_name in file_names:
        file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'files', file_name))
        print(f"Uploading file {file_path}")
        file = await ai_client.agents.upload_file_and_poll(file_path=file_path, purpose=FilePurpose.AGENTS)
        files.update({file.id: file_path})
    
    vector_store = await ai_client.agents.create_vector_store_and_poll(file_ids=list(files.keys()), name="sample_store")

    file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])
    
    tool_set = AsyncToolSet()
    tool_set.add(file_search_tool)
    
    print(f"ToolResource: {tool_set.resources}")
        
    agent = await ai_client.agents.create_agent(
        model="gpt-4o-mini", name="my-assistant", instructions="You are helpful assistant", tools = tool_set.definitions, tool_resources=tool_set.resources
    )
    
    print(f"Created agent, agent ID: {agent.id}")

    bp.ai_client = ai_client
    bp.agent = agent
    bp.vector_store = vector_store
    bp.files = files
    
    yield

    await stop_server()  
        

async def stop_server():
    for file_id in bp.files.keys():
        await bp.ai_client.agents.delete_file(file_id)
        print(f"Deleted file {file_id}")
    
    await bp.ai_client.agents.delete_vector_store(bp.vector_store.id)
    print(f"Deleted vector store {bp.vector_store.id}")
    
    await bp.ai_client.agents.delete_agent(bp.agent.id)

    print(f"Deleted agent {bp.agent.id}")        
    
    await bp.ai_client.close()
    print("Closed AIProjectClient")



def create_app():
    if not os.getenv("RUNNING_IN_PRODUCTION"):
        logger.info("Loading .env file")
        load_dotenv(override=True)

    directory = os.path.join(os.path.dirname(__file__), "static")
    app = fastapi.FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=directory), name="static")

    from . import routes  # noqa

    app.include_router(routes.router)

    return app
