# Sample Application using Agents from Azure AI Projects and File Search tool (Python)

This sample includes a simple Python [Quart](https://quart.palletsprojects.com/en/latest/) app that streams responses from Azure AI Agents to an HTML/JS frontend using Server-Sent Events (SSEs). The application is configured to upload two documents under the `files` folder for use with the Azure AI Agents' File Search tool.

The sample is designed for use with [Docker containers](https://www.docker.com/), both for local development and Azure deployment. For Azure deployment to [Azure Container Apps](https://learn.microsoft.com/azure/container-apps/overview), please use this [template](https://github.com/Azure-Samples/openai-chat-app-quickstart) and replace the `src` folder content with this application.

## Application Flow

This application utilizes agents from the azure-ai-projects SDK to interact with the Azure ML agents API. The following sequence diagram describes the interaction between each component in the system. More comprehensive logic related to thread management will be discussed in the next section:

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant WebServer
    participant APIServer

    WebServer->>APIServer: upload_file_poll (post file API and poll by get)
    APIServer-->>WebServer: return file
    WebServer->>APIServer: create_vector_store_and_poll (post vector store API and poll by get)
    APIServer-->>WebServer: return vector store
    WebServer->>APIServer: create_agent (post assistant API)
    APIServer-->>WebServer: return agent

    User->>Browser: Open 'http://localhost:50505'
    Browser->>WebServer: /index
    WebServer-->>Browser: return HTML, JavaScript, CSS

    User->>Browser: Type message and hit enter
    Browser->>WebServer: /chat
    WebServer->>APIServer: create_thread (post thread API)
    APIServer-->>WebServer: return thread

    WebServer->>APIServer: create_message (post message API)
    APIServer-->>WebServer: return message

    WebServer->>APIServer: create_stream (post run API)
    APIServer-->>WebServer: return chunk
    WebServer-->>Browser: return chunk  (thread_id, agent_id in cookie)
```

## Application Users and Thread Management

As a web application, it is designed to serve multiple users on multiple browsers. This application uses cookies to ensure that the same thread is reused for conversations across multiple tabs in the same browser. If the browser is restarted, the old thread will continue to serve the user. However, if the application has a new agent after a server restart or a thread is deleted, a new thread will be created without requiring a browser refresh or signaling to the users.

To achieve this, when users submit a message to the web server, the web server will create an agent, thread, and stream back a reply. The response contains `agent_id` and `thread_id` in cookies. As a result, each subsequent message sent to the web server will also contain these IDs. As long as the same agent is being used in the system and the thread can be retrieved in the cookie, the same thread will be used to serve the users.

## Local Development

1. Run `pip install -r ./src/requirements.txt`.

2. Make sure that the `.env` file exists.

3. Store the Azure AI Projects connection string in the `.env` file as `PROJECT_CONNECTION_STRING`.

4. Run `az login`.

5. Start the services with this command:

    ```shell
    python -m uvicorn "api.main:create_app" --app-dir src --port 50505 --reload
    ```

6. Click 'http://localhost:50505' in the browser to run the application.

## Example Run

![File-Search-screenshot](assets/FileSearchAgent.png)

## Deployment to Azure

Follow these steps for deployment:
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/). If you opened this inside GitHub Codespaces or a Dev Container in VS Code, installation is not needed. ⚠️ If you're on an Apple M1/M2, you won't be able to run `docker` commands inside a Dev Container; either use Codespaces or do not open the Dev Container.
2. Integrate this app using [template](https://github.com/Azure-Samples/openai-chat-app-quickstart) and follow the Azure Container App deployment steps there.
3. Add an entry of environment variable, `PROJECT_CONNECTION_STRING` in `infra\aca.bicep`.
4. When you visit the Azure Container App, you will see the deployment has a permission error in the `Console Log`.

![Deployment-Error](assets/DeploymentError.png)

To resolve this permission issue, you need to assign `Contributor` and `Cognitive Services OpenAI User` roles for this `object id` in the `Resource Group` of the `Azure AI Projects`.
