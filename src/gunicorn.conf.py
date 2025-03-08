# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license.
# See LICENSE file in the project root for full license information.
from typing import Dict

import asyncio
import csv
import json
import logging
import multiprocessing
import os
import sys

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import (
    Agent,
    AsyncToolSet,
    AzureAISearchTool,
    ConnectionType,
    FilePurpose,
    FileSearchTool,
)
from azure.identity.aio import DefaultAzureCredential
from azure.core.credentials_async import AsyncTokenCredential


# Create a central logger for the application
logger = logging.getLogger("azureaiapp")
logger.setLevel(logging.INFO)

# Configure the stream handler (stdout)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
stream_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
stream_handler.setFormatter(stream_formatter)
logger.addHandler(stream_handler)

# Configure logging to file, if log file name is provided
log_file_name = os.getenv("APP_LOG_FILE", "")
if log_file_name != "":
    file_handler = logging.FileHandler(log_file_name)
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

FILES_NAMES = ["product_info_1.md", "product_info_2.md"]


async def create_index_maybe(
        ai_client: AIProjectClient, creds: AsyncTokenCredential) -> None:
    """
    Create the index and upload documents if the index does not exist.

    This code is executed only once, when called on_starting hook is being
    called. This code ensures that the index is being populated only once.
    rag.create_index return True if the index was created, meaning that this
    docker node have started first and must populate index.

    :param ai_client: The project client to be used to create an index.
    :param creds: The credentials, used for the index.
    """
    from api.search_index_manager import SearchIndexManager
    endpoint = os.environ.get('AZURE_AI_SEARCH_ENDPOINT')
    if endpoint:
        aoai_connection = await ai_client.connections.get_default(
            connection_type=ConnectionType.AZURE_OPEN_AI,
            include_credentials=True)
        if aoai_connection is None or aoai_connection.key is None:
            err = "Error getting the connection to Azure Open AI service. {}"
            if aoai_connection is not None and aoai_connection.key is None:
                logger.error(
                    err.format(
                        "Please configure "
                        f"{aoai_connection.name} to use API key."))
            else:
                logger.error(
                    err.format("Azure Open AI service connection is absent."))
            return
        search_mgr = SearchIndexManager(
            endpoint=endpoint,
            credential=creds,
            index_name=os.getenv('AZURE_AI_SEARCH_INDEX_NAME'),
            dimensions=None,
            model=os.getenv('AZURE_AI_EMBED_DEPLOYMENT_NAME'),
            deployment_name=os.getenv('AZURE_AI_EMBED_DEPLOYMENT_NAME'),
            embedding_endpoint=aoai_connection.endpoint_url,
            embed_api_key=aoai_connection.key
        )
        # If another application instance already have created the index,
        # do not upload the documents.
        if await search_mgr.create_index(
            vector_index_dimensions=int(
                os.getenv('AZURE_AI_EMBED_DIMENSIONS'))):
            embeddings_path = os.path.join(
                os.path.dirname(__file__), 'data', 'embeddings.csv')

            assert embeddings_path, f'File {embeddings_path} not found.'
            await search_mgr.upload_documents(embeddings_path)
            await search_mgr.close()


def _get_file_path(file_name: str) -> str:
    """
    Get absolute file path.

    :param file_name: The file name.
    """
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__),
                     'files',
                     file_name))


async def get_available_toolset(
        ai_client: AIProjectClient,
        creds: AsyncTokenCredential) -> AsyncToolSet:
    """
    Get the toolset and tool definition for the agent.

    :param ai_client: The project client to be used to create an index.
    :param creds: The credentials, used for the index.
    :return: The tool set, available based on the environment.
    """
    # First try to get an index search.
    conn_id = ""
    if os.environ.get('AZURE_AI_SEARCH_INDEX_NAME'):
        conn_list = await ai_client.connections.list()
        for conn in conn_list:
            if conn.connection_type == ConnectionType.AZURE_AI_SEARCH:
                conn_id = conn.id
                break

    toolset = AsyncToolSet()
    if conn_id:
        await create_index_maybe(ai_client, creds)

        ai_search = AzureAISearchTool(
            index_connection_id=conn_id,
            index_name=os.environ.get('AZURE_AI_SEARCH_INDEX_NAME'))

        toolset.add(ai_search)
        logger.info("agent: initialized index")
    else:
        logger.info(
            "agent: index was not initialized, falling back to file search.")
        # File name -> {"id": file_id, "path": file_path}
        files: Dict[str, Dict[str, str]] = {}
        # Upload files for file search
        for file_name in FILES_NAMES:
            file_path = _get_file_path(file_name)
            file = await ai_client.agents.upload_file_and_poll(
                file_path=file_path, purpose=FilePurpose.AGENTS)
            # Store both file id and the file path using the file name as key.
            files[file_name] = {"id": file.id, "path": file_path}

        # Serialize and store files information in the environment variable (so
        # workers see it)
        os.environ["UPLOADED_FILE_MAP"] = json.dumps(files)
        logger.info(
            f"Set env UPLOADED_FILE_MAP = {os.environ['UPLOADED_FILE_MAP']}")

        # Create the vector store using the file IDs.
        vector_store = await ai_client.agents.create_vector_store_and_poll(
            file_ids=[info["id"] for info in files.values()],
            name="sample_store"
        )
        logger.info("agent: file store and vector store success")

        file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])
        toolset.add(file_search_tool)

    return toolset


async def create_agent(ai_client: AIProjectClient,
                       creds: AsyncTokenCredential) -> Agent:
    logger.info("Creating new agent with resources")

    agent = await ai_client.agents.create_agent(
        model=os.environ["AZURE_AI_AGENT_DEPLOYMENT_NAME"],
        name=os.environ["AZURE_AI_AGENT_NAME"],
        instructions="You are helpful assistant",
        toolset=await get_available_toolset(ai_client, creds)
    )
    return agent


async def update_agent(agent: Agent, ai_client: AIProjectClient,
                       creds: AsyncTokenCredential) -> Agent:
    logger.info("Updating agent with resources")

    agent = await ai_client.agents.update_agent(
        assistant_id=agent.id,
        model=os.environ["AZURE_AI_AGENT_DEPLOYMENT_NAME"],
        name=os.environ["AZURE_AI_AGENT_NAME"],
        instructions="You are helpful assistant",
        toolset=await get_available_toolset(ai_client, creds)
    )
    return agent


async def initialize_resources():
    try:
        async with DefaultAzureCredential(
                exclude_shared_token_cache_credential=True) as creds:
            async with AIProjectClient.from_connection_string(
                credential=creds,
                conn_str=os.environ["AZURE_AIPROJECT_CONNECTION_STRING"],
            ) as ai_client:

                # If the environment already has AZURE_AI_AGENT_ID, try
                # fetching that agent
                if os.environ.get("AZURE_AI_AGENT_ID") is not None:
                    try:
                        agent = await ai_client.agents.get_agent(
                            os.environ["AZURE_AI_AGENT_ID"])
                        logger.info(f"Found agent by ID: {agent.id}")
                        # Update the agent with the latest resources
                        agent = await update_agent(agent, ai_client, creds)
                        return
                    except Exception as e:
                        logger.warning(
                            "Could not retrieve agent by AZURE_AI_AGENT_ID = "
                            f"{os.environ['AZURE_AI_AGENT_ID']}, error: {e}")

                # Check if an agent with the same name already exists
                agent_list = await ai_client.agents.list_agents()
                if agent_list.data:
                    for agent_object in agent_list.data:
                        if agent_object.name == os.environ[
                                "AZURE_AI_AGENT_NAME"]:
                            logger.info(
                                "Found existing agent named "
                                f"'{agent_object.name}'"
                                f", ID: {agent_object.id}")
                            os.environ["AZURE_AI_AGENT_ID"] = agent_object.id
                            # Update the agent with the latest resources
                            agent = await update_agent(
                                agent_object, ai_client, creds)
                            return

                # Create a new agent
                agent = await create_agent(ai_client, creds)
                os.environ["AZURE_AI_AGENT_ID"] = agent.id
                logger.info(f"Created agent, agent ID: {agent.id}")

    except Exception as e:
        logger.info("Error creating agent: {e}", exc_info=True)
        raise RuntimeError(f"Failed to create the agent: {e}")


def on_starting(server):
    """This code runs once before the workers will start."""
    asyncio.get_event_loop().run_until_complete(initialize_resources())


max_requests = 1000
max_requests_jitter = 50
log_file = "-"
bind = "0.0.0.0:50505"

if not os.getenv("RUNNING_IN_PRODUCTION"):
    reload = True

# Load application code before the worker processes are forked.
# Needed to execute on_starting.
# Please see the documentation on gunicorn
# https://docs.gunicorn.org/en/stable/settings.html
preload_app = True
num_cpus = multiprocessing.cpu_count()
workers = (num_cpus * 2) + 1
worker_class = "uvicorn.workers.UvicornWorker"

timeout = 120
