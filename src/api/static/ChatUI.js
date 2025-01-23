// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE.md file in the project root for full license information.

class ChatUI {
    constructor() {
        this.targetContainer = document.getElementById("messages");
        this.userTemplate = document.querySelector('#message-template-user');
        this.assistantTemplate = document.querySelector('#message-template-assistant');
        if (!this.assistantTemplate) {
            console.error("Assistant template not found!");
        }
        this.addCitationClickListener();
        this.attachCloseButtonListener();
    }

    preprocessContent(content, annotations) {
        if (annotations) {  
            annotations.slice().reverse().forEach(annotation => {
                // the start and end index are the label of annotation. Replace them with a link
                content = content.slice(0, annotation.start_index) +
                `<a href="#" class="file-citation" data-file-id="${annotation.file_citation.file_id}">${annotation.text}</a>` +
                content.slice(annotation.end_index);
            });
        }
        return content;
      }

    addCitationClickListener() {
        document.addEventListener('click', (event) => {
            if (event.target.classList.contains('file-citation')) {
                event.preventDefault();
                const file_id = event.target.getAttribute('data-file-id');
                this.loadDocument(file_id);
            }
        });
    }

    async loadDocument(file_id) {
        try {
            const response = await fetch(`/fetch-document?file_id=${file_id}`);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const markdownContent = await response.text();
            // Use markdown-it to convert Markdown to HTML
            const md = window.markdownit({
                html: true,
                linkify: true,
                typographer: true,
                breaks: true
            });
            const htmlContent = md.render(markdownContent);
            this.showDocument(htmlContent);
        } catch (error) {
            console.error('Error fetching document:', error);
        }
    }

    showDocument(content) {
        const docViewerSection = document.getElementById("document-viewer-section");
        const chatColumn = document.getElementById("chat-container");

        // Load the document content into the iframe
        const iframe = document.getElementById("document-viewer");
        iframe.srcdoc = content;

        // Check if the iframe content is loaded correctly
        iframe.onload = function() {
            console.log("Iframe loaded successfully.");
        };
        iframe.onerror = function() {
            console.error("Error loading iframe content.");
        };

        // Update Bootstrap grid classes for splitting the screen
        chatColumn.classList.remove("col-full");
        chatColumn.classList.add("col-half");
        docViewerSection.classList.add("visible");
        docViewerSection.classList.remove("hidden");

        // Make the document viewer and the close button visible
        docViewerSection.style.display = 'block';
        document.getElementById("close-button").style.display = 'block';
    }

    closeDocumentViewer() {
        const docViewerSection = document.getElementById("document-viewer-section");
        const chatColumn = document.getElementById("chat-container");

        // Hide the document viewer and the close button
        docViewerSection.style.display = 'none';
        docViewerSection.classList.add("hidden");
        docViewerSection.classList.remove("visible");
        document.getElementById("close-button").style.display = 'none';

        // Restore the chat column to full width
        chatColumn.classList.remove("col-half");
        chatColumn.classList.add("col-full");
    }

    attachCloseButtonListener() {
        const closeButton = document.getElementById("close-button");
        if (closeButton) {
            closeButton.addEventListener("click", () => this.closeDocumentViewer());
        }
    }

    appendUserMessage(message) {
        const userTemplateClone = this.userTemplate.content.cloneNode(true);
        userTemplateClone.querySelector(".message-content").textContent = message;
        this.targetContainer.appendChild(userTemplateClone);
        this.scrollToBottom();
    }

    appendAssistantMessage(messageDiv, accumulatedContent, isStreaming, annotations) {
        const md = window.markdownit({
            html: true,
            linkify: true,
            typographer: true,
            breaks: true
        });
    
        try {
            // Preprocess content to convert citations to links
            const preprocessedContent = this.preprocessContent(accumulatedContent, annotations);
            // Convert the accumulated content to HTML using markdown-it
            let htmlContent = md.render(preprocessedContent);
            const messageTextDiv = messageDiv.querySelector(".message-text");
            if (!messageTextDiv) {
                throw new Error("Message content div not found in the template.");
            }
    
            // Set the innerHTML of the message text div to the HTML content
            messageTextDiv.innerHTML = htmlContent;
            
            // Use requestAnimationFrame to ensure the DOM has updated before scrolling
            // Only scroll if not streaming
            if (!isStreaming) {
                requestAnimationFrame(() => {
                    this.scrollToBottom();
                });
            }
        } catch (error) {
            console.error("Error in appendAssistantMessage:", error);
        }
    }

    clearAssistantMessage(messageDiv) {
        const messageTextDiv = messageDiv.querySelector(".message-text");
        if (messageTextDiv) {
            messageTextDiv.innerHTML = '';
        }
    }

    createAssistantMessageDiv() {
        const assistantTemplateClone = this.assistantTemplate.content.cloneNode(true);
        if (!assistantTemplateClone) {
            console.error("Failed to clone assistant template.");
            return null;
        }
    
        // Append the clone to the target container
        this.targetContainer.appendChild(assistantTemplateClone);
    
        // Since the content of assistantTemplateClone is now transferred to the DOM,
        // you should query the targetContainer for the elements you want to interact with.
        // Specifically, you look at the last added 'toast' which is where the new content lives.
        const newlyAddedToast = this.targetContainer.querySelector(".toast-container:last-child .toast:last-child");
       
        if (!newlyAddedToast) {
            console.error("Failed to find the newly added toast element.");
            return null;
        }
    
        // Now, find the .message-content within this newly added toast
        const messageDiv = newlyAddedToast.querySelector(".message-content");
    
        if (!messageDiv) {
            console.error("Message content div not found in the template.");
        }
    
        return messageDiv;
    }
    
    scrollToBottom() {
        const lastChild = this.targetContainer.lastElementChild;
        if (lastChild) {
            // Adjust the scroll to make sure the input box is visible
            lastChild.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
        
        // Ensure the input box remains visible
        const inputBox = document.querySelector('#chat-area');
        if (inputBox) {
            inputBox.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }
}

export default ChatUI;
