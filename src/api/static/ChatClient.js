// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE.md file in the project root for full license information.

class ChatClient {
    constructor(ui) {
        this.ui = ui;
    }

    async sendMessage(url, message) {
        if (!message) return false;

        this.ui.appendUserMessage(message);

        let postData = {message: message};

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(postData)
            });

            if (!response.body) {
                throw new Error('ReadableStream not supported');
            }

            this.handleMessages(response.body);
        } catch (error) {
            console.error('Fetch failed:', error);
        }
}
    
    handleMessages(stream) {
        let messageDiv = null;
        let accumulatedContent = '';
        let isStreaming = true;
        let buffer = '';
        let annotations = [];
    
        const reader = stream.getReader();
        const decoder = new TextDecoder();
    
        const readStream = async () => {
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }
    
                buffer += decoder.decode(value, { stream: true });
    
                let boundary = buffer.indexOf('\n');
                while (boundary !== -1) {
                    const chunk = buffer.slice(0, boundary).trim();
                    buffer = buffer.slice(boundary + 1);
    
                    if (chunk.startsWith('data: ')) {
                        const data = JSON.parse(chunk.slice(6));
    
                        if (data.type === "stream_end") {
                            reader.releaseLock();
                            messageDiv = null;
                            accumulatedContent = '';
                        } else {
                            if (!messageDiv) {
                                messageDiv = this.ui.createAssistantMessageDiv();
                                if (!messageDiv) {
                                    console.error("Failed to create message div.");
                                }
                            }
    
                            if (data.type === "completed_message") {
                                this.ui.clearAssistantMessage(messageDiv);
                                accumulatedContent = data.content;
                                annotations = data.annotations;
                                isStreaming = false;
                            } else {
                                accumulatedContent += data.content;
                            }
    
                            this.ui.appendAssistantMessage(messageDiv, accumulatedContent, isStreaming, annotations);
                        }
                    }
    
                    boundary = buffer.indexOf('\n');
                }
            }
        };
    
        readStream().catch(error => {
            console.error('Stream reading failed:', error);
        });
    }

}

export default ChatClient;
