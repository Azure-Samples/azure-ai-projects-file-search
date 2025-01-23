# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE.md file in the project root for full license information.

from typing import AsyncGenerator, Dict, Optional, Tuple

import asyncio
import json, os


from azure.ai.projects.models import (
    MessageDeltaChunk,
    ThreadMessage,
    ThreadMessage,
    AsyncAgentEventHandler,
)


import json

import fastapi
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .shared import bp


router = fastapi.APIRouter()
directory = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=directory)



class MyEventHandler(AsyncAgentEventHandler[str]):

    async def on_message_delta(
        self, delta: "MessageDeltaChunk" 
    ) -> Optional[str]:
        stream_data = json.dumps({'content': delta.text, 'type': "message"})
        return f"data: {stream_data}\n\n"

    async def on_thread_message(
        self, message: "ThreadMessage" 
    ) -> Optional[str]:
        if message.status == "completed":
            annotations = [annotation.as_dict() for annotation in message.file_citation_annotations]
            stream_data = json.dumps({'content': message.text_messages[0].text.value, 'annotations': annotations, 'type': "completed_message"})
            return f"data: {stream_data}\n\n"
        return None

    async def on_error(self, data: str) -> Optional[str]:
        print(f"An error occurred. Data: {data}")
        stream_data = json.dumps({'type': "stream_end"})
        return f"data: {stream_data}\n\n"

    async def on_done(
        self,
    ) -> Optional[str]:
        stream_data = json.dumps({'type': "stream_end"})
        return f"data: {stream_data}\n\n"




@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

    

async def get_result(thread_id: str, agent_id: str) -> AsyncGenerator[str, None]:
    async with await bp.ai_client.agents.create_stream(
        thread_id=thread_id, assistant_id=agent_id,
        event_handler=MyEventHandler()
    ) as stream:
        # Iterate over the steam to trigger event functions
        async for _, _, event_func_return_val in stream:
            if event_func_return_val:
                yield event_func_return_val
                
@router.post("/chat")
async def chat(request: Request):
    thread_id = request.cookies.get('thread_id')
    agent_id = request.cookies.get('agent_id')
    thread = None
    
    if thread_id and agent_id == bp.agent.id:
        # Check if the thread is still active
        try:
            thread = await bp.ai_client.agents.get_thread(thread_id)
        except Exception as e:
            return fastapi.responses.JSONResponse(content={"error": f"Failed to retrieve thread with ID {thread_id}: {e}"}, status_code=400)
    if thread is None:
        thread = await bp.ai_client.agents.create_thread()    
                    
    thread_id = thread.id
    agent_id = bp.agent.id    
    user_message = await request.json()
    
    print(f"user_message: {user_message}")

    if not hasattr(bp, 'ai_client'):
        return fastapi.responses.JSONResponse(content={"error": "Agent is not initialized"}, status_code=500)

    message = await bp.ai_client.agents.create_message(
        thread_id=thread.id, role="user", content=user_message['message']
    )
    print(f"Created message, message ID {message.id}")


    # Set necessary headers for SSE
    headers = {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Content-Type': 'text/event-stream'
    }

    response = fastapi.responses.StreamingResponse(get_result(thread_id, agent_id), headers=headers)
    response.set_cookie('thread_id', thread_id)
    response.set_cookie('agent_id', agent_id)    
    return response

@router.get("/fetch-document")
async def fetch_document(request: Request):
    file_id = request.query_params.get('file_id')
    if not file_id:
        raise fastapi.HTTPException(status_code=400, detail="file_id is required")

    try:
        # Read the file content asynchronously using asyncio.to_thread
        data = await asyncio.to_thread(read_file, bp.files[file_id])
        return fastapi.responses.PlainTextResponse(data)

    except Exception as e:
        return fastapi.responses.JSONResponse(content={"error": str(e)}, status_code=500)

def read_file(path):
    with open(path, 'r') as file:
        return file.read()
