// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE.md file in the project root for full license information.

import ChatUI from './ChatUI.js';
import ChatClient from './ChatClient.js';

function initChat() {
    const chatUI = new ChatUI();
    const chatClient = new ChatClient(chatUI);

    const form = document.getElementById("chat-form");

    const messageInput = document.getElementById("message");


    form.addEventListener("submit", async function(e) {
        e.preventDefault();
        await chatClient.sendMessage("/chat", messageInput.value.trim());
        messageInput.value = "";
    });

    window.onbeforeunload = function() {
        chatClient.closeEventSource();
    };
}

document.addEventListener("DOMContentLoaded", initChat);
