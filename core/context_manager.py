#!/usr/bin/env python3
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class ContextManager:
    """Manages conversation context with sliding window memory."""
    
    def __init__(self, system_prompt: str, max_history: int = 8, max_tokens: int = 4096):
        """Initialize the context manager.
        
        Args:
            system_prompt: System prompt to always include
            max_history: Maximum number of conversation turns to keep
            max_tokens: Maximum number of tokens in context (approximate)
        """
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.max_tokens = max_tokens
        self.history: List[Dict[str, str]] = []
        self.summary: Optional[str] = None
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history.
        
        Args:
            role: Message role (user, assistant, system)
            content: Message content
        """
        self.history.append({"role": role, "content": content})
        
        # Apply sliding window if history gets too long
        if len(self.history) > self.max_history + 2:  # +2 to allow some buffer
            self._apply_sliding_window()
    
    def _apply_sliding_window(self) -> None:
        """Apply sliding window to maintain context within limits."""
        # Always keep the most recent messages
        keep_recent = min(self.max_history // 2, 3)  # Keep at least the most recent 3 messages
        
        # Calculate approximate token count
        # This is a very rough estimation: ~4 chars per token
        current_tokens = sum(len(msg["content"]) // 4 for msg in self.history)
        
        if current_tokens > self.max_tokens * 0.8:  # If we're using 80% of our budget
            logger.info(f"Applying sliding window, current tokens ~{current_tokens}")
            
            # Keep system messages, recent messages, and create a bridge summary
            system_messages = [msg for msg in self.history if msg["role"] == "system"]
            recent_messages = self.history[-keep_recent:]
            
            # Create a bridge summary of the last topic before pruning
            topic_messages = self.history[-(keep_recent+4):-keep_recent]
            if topic_messages:
                bridge_summary = self._create_bridge_summary(topic_messages)
                bridge_message = {"role": "system", "content": f"Previous conversation summary: {bridge_summary}"}
            else:
                bridge_message = None
            
            # Update history: system messages + optional bridge + recent messages
            new_history = system_messages.copy()
            if bridge_message:
                new_history.append(bridge_message)
            new_history.extend(recent_messages)
            
            self.history = new_history
            
            # Log the change
            new_tokens = sum(len(msg["content"]) // 4 for msg in self.history)
            logger.info(f"Reduced context from ~{current_tokens} to ~{new_tokens} tokens")
    
    def _create_bridge_summary(self, messages: List[Dict[str, str]]) -> str:
        """Create a simple summary of previous messages to bridge context.
        
        Args:
            messages: List of messages to summarize
            
        Returns:
            Summary string
        """
        # Extract user questions
        user_messages = [msg["content"] for msg in messages if msg["role"] == "user"]
        
        if not user_messages:
            return "No previous context."
        
        # For simplicity, just use the last user message as the topic indicator
        last_topic = user_messages[-1]
        
        # Truncate to reasonable length
        if len(last_topic) > 100:
            last_topic = last_topic[:97] + "..."
        
        return f"You were discussing: {last_topic}"
    
    def get_context(self) -> List[Dict[str, str]]:
        """Get the current context including system prompt and history.
        
        Returns:
            List of message dictionaries for context
        """
        # Always start with the system prompt
        context = [{"role": "system", "content": self.system_prompt}]
        
        # Add the history
        context.extend(self.history)
        
        return context
    
    def get_system_prompt(self) -> str:
        """Get the system prompt.
        
        Returns:
            System prompt string
        """
        return self.system_prompt
    
    def clear_history(self) -> None:
        """Clear the conversation history."""
        self.history = []
        self.summary = None
    
    def get_last_user_message(self) -> Optional[str]:
        """Get the last message from the user.
        
        Returns:
            Last user message or None if no user messages
        """
        for message in reversed(self.history):
            if message["role"] == "user":
                return message["content"]
        return None
    
    def get_last_assistant_message(self) -> Optional[str]:
        """Get the last message from the assistant.
        
        Returns:
            Last assistant message or None if no assistant messages
        """
        for message in reversed(self.history):
            if message["role"] == "assistant":
                return message["content"]
        return None
    
    def format_for_prompt(self) -> str:
        """Format the conversation history for inclusion in a prompt.
        
        Returns:
            Formatted conversation string
        """
        formatted = []
        
        for message in self.history:
            role = message["role"].capitalize()
            content = message["content"]
            
            if role == "System":
                continue  # Skip system messages in the formatted output
            
            formatted.append(f"{role}: {content}")
        
        return "\n\n".join(formatted)
