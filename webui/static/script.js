// Neuro-Lite Web UI JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize components
    const md = window.markdownit({
        html: false,
        linkify: true,
        typographer: true,
        highlight: function(str, lang) {
            if (lang && hljs.getLanguage(lang)) {
                try {
                    return hljs.highlight(str, { language: lang }).value;
                } catch (__) {}
            }
            return ''; // use external default escaping
        }
    });
    
    // DOM elements
    const chatMessages = document.getElementById('chat-messages');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const newChatButton = document.getElementById('new-chat');
    const exportChatButton = document.getElementById('export-chat');
    const typingIndicator = document.getElementById('typing-indicator');
    const statusDisplay = document.getElementById('status');
    
    // State
    let conversationId = null;
    let isProcessing = false;
    
    // Initialize app
    function init() {
        // Setup event listeners
        userInput.addEventListener('keydown', handleInputKeydown);
        sendButton.addEventListener('click', sendMessage);
        newChatButton.addEventListener('click', startNewChat);
        exportChatButton.addEventListener('click', exportChat);
        
        // Focus input
        userInput.focus();
        
        // Check connection to backend
        checkConnection();
    }
    
    // Check connection to backend
    async function checkConnection() {
        try {
            const response = await fetch('/api/health');
            if (response.ok) {
                const data = await response.json();
                statusDisplay.textContent = `Connected (v${data.version})`;
                statusDisplay.style.color = '#4CAF50';
            } else {
                throw new Error('Connection failed');
            }
        } catch (error) {
            statusDisplay.textContent = 'Disconnected';
            statusDisplay.style.color = '#F44336';
            console.error('Connection error:', error);
        }
    }
    
    // Handle input keydown
    function handleInputKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }
    
    // Start a new chat
    function startNewChat() {
        if (confirm('Start a new conversation? This will clear the current chat.')) {
            conversationId = null;
            chatMessages.innerHTML = `
                <div class="message assistant">
                    <div class="message-content markdown-body">
                        <p>Hello! I'm Neuro-Lite, a lightweight AI assistant. How can I help you today?</p>
                    </div>
                </div>
            `;
            userInput.value = '';
            userInput.focus();
        }
    }
    
    // Export chat to file
    function exportChat() {
        // Get all messages
        const messages = [];
        document.querySelectorAll('.message').forEach(messageEl => {
            const role = messageEl.classList.contains('user') ? 'User' : 'Assistant';
            const content = messageEl.querySelector('.message-content').textContent;
            messages.push(`${role}: ${content.trim()}`);
        });
        
        // Create file content
        const fileContent = messages.join('\n\n');
        const blob = new Blob([fileContent], { type: 'text/plain' });
        
        // Create download link
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `neuro-lite-chat-${new Date().toISOString().slice(0, 10)}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
    
    // Send a message
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message || isProcessing) return;
        
        // Set processing state
        isProcessing = true;
        
        // Disable input during processing
        userInput.value = '';
        userInput.disabled = true;
        sendButton.disabled = true;
        
        // Add user message to chat
        addMessage(message, 'user');
        
        // Show typing indicator
        typingIndicator.style.display = 'flex';
        
        try {
            // Use streaming endpoint
            const response = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    message: message,
                    stream: true
                })
            });
            
            if (!response.ok) {
                throw new Error(`Error: ${response.status}`);
            }
            
            // Process the stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let assistantMessageElement = null;
            let assistantMessageContent = '';
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                // Decode and process the chunk
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n\n');
                
                for (const line of lines) {
                    if (!line.trim() || !line.startsWith('data: ')) continue;
                    
                    try {
                        const data = JSON.parse(line.substring(6));
                        
                        if (data.type === 'start') {
                            // Start of response
                            conversationId = data.conversation_id;
                            assistantMessageContent = '';
                            assistantMessageElement = document.createElement('div');
                            assistantMessageElement.className = 'message assistant';
                            const contentElement = document.createElement('div');
                            contentElement.className = 'message-content markdown-body';
                            assistantMessageElement.appendChild(contentElement);
                            chatMessages.appendChild(assistantMessageElement);
                        } else if (data.type === 'token') {
                            // Token received
                            assistantMessageContent += data.token;
                            if (assistantMessageElement) {
                                const contentElement = assistantMessageElement.querySelector('.message-content');
                                contentElement.innerHTML = md.render(assistantMessageContent);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                        } else if (data.type === 'end') {
                            // End of response with final formatted message
                            if (assistantMessageElement) {
                                const contentElement = assistantMessageElement.querySelector('.message-content');
                                contentElement.innerHTML = md.render(data.message);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                                
                                // Apply syntax highlighting to code blocks
                                assistantMessageElement.querySelectorAll('pre code').forEach(block => {
                                    hljs.highlightElement(block);
                                });
                            }
                        } else if (data.type === 'error') {
                            throw new Error(data.error);
                        }
                    } catch (error) {
                        console.error('Error processing stream chunk:', error);
                    }
                }
            }
        } catch (error) {
            console.error('Error sending message:', error);
            addMessage(`I'm sorry, I encountered an error. Please try again later.`, 'assistant');
        } finally {
            // Re-enable input
            userInput.disabled = false;
            sendButton.disabled = false;
            typingIndicator.style.display = 'none';
            userInput.focus();
            
            // Scroll to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            // Reset processing state
            isProcessing = false;
        }
    }
    
    // Add a message to the chat
    function addMessage(content, role) {
        const messageElement = document.createElement('div');
        messageElement.className = `message ${role}`;
        
        const contentElement = document.createElement('div');
        contentElement.className = 'message-content markdown-body';
        
        if (role === 'user') {
            contentElement.textContent = content;
        } else {
            contentElement.innerHTML = md.render(content);
        }
        
        messageElement.appendChild(contentElement);
        chatMessages.appendChild(messageElement);
        
        // Apply syntax highlighting to code blocks
        if (role === 'assistant') {
            messageElement.querySelectorAll('pre code').forEach(block => {
                hljs.highlightElement(block);
            });
        }
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    
    // Initialize the app
    init();
});
