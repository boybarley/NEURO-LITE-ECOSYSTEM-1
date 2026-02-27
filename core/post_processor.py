#!/usr/bin/env python3
import re
import time
import logging
import random
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class PostProcessor:
    """Process model outputs to add empathy and professional formatting."""
    
    # Greeting templates for different emotional states
    GREETING_TEMPLATES = {
        "neutral": [
            "I'd like to help with that.",
            "Here's what you need to know.",
            "Let me address that for you.",
            "I can provide some information on this.",
            ""  # Empty string for cases where no greeting is needed
        ],
        "concerned": [
            "I understand your concern. ",
            "I see this is important to you. ",
            "I appreciate you bringing this up. ",
            "I can help address this issue. ",
            "Let me help with this concern. "
        ],
        "celebratory": [
            "That's great news! ",
            "I'm glad to hear that! ",
            "That's wonderful! ",
            "Excellent! ",
            "That's something to celebrate! "
        ],
        "frustrated": [
            "I understand your frustration. ",
            "I see this has been challenging. ",
            "Let me help resolve this issue. ",
            "I appreciate your patience. ",
            "I'll do my best to address this. "
        ],
        "curious": [
            "That's an interesting question. ",
            "I'd be happy to explain. ",
            "Great question. ",
            "I can help you understand this. ",
            "Let me share what I know about this. "
        ]
    }
    
    # Closing templates
    CLOSING_TEMPLATES = {
        "neutral": [
            "Hope this helps.",
            "Let me know if you have further questions.",
            "",  # Empty string for cases where no closing is needed
            "Is there anything else you'd like to know?",
            ""
        ],
        "concerned": [
            "Hope this addresses your concern.",
            "Let me know if you need further assistance.",
            "I hope that helps resolve the issue.",
            "Feel free to ask if anything isn't clear.",
            "Is there anything else you're concerned about?"
        ],
        "celebratory": [
            "Congratulations again!",
            "Keep up the great work!",
            "That's really something to be proud of.",
            "I'm happy for your success.",
            "Anything else you'd like to celebrate?"
        ],
        "frustrated": [
            "Hope this helps address the issue.",
            "Let me know if you need further clarification.",
            "I hope that resolves your concern.",
            "Feel free to ask if something isn't working.",
            "Is there anything else I can help with?"
        ],
        "curious": [
            "Hope that satisfies your curiosity.",
            "Let me know if you'd like to explore further.",
            "Is there anything else you're curious about?",
            "Feel free to ask more questions.",
            "Hope this explanation helps."
        ]
    }
    
    # Formatting patterns
    FORMATTING_PATTERNS = [
        # Add bold to headings (lines ending with : or starting with #)
        (r'^(#+\s*)(.*)', r'**\1\2**'),
        (r'^([^:\n]+):\s*$', r'**\1:**'),
        
        # Convert - list items to proper Markdown bullet points
        (r'(?m)^- (.+)$', r'* \1'),
        
        # Add line break after paragraphs
        (r'(\n\n)', r'\1'),
        
        # Fix multiple newlines
        (r'\n{3,}', r'\n\n'),
        
        # Ensure proper code formatting
        (r'`([^`]+)`', r'`\1`'),
    ]
    
    def __init__(self):
        """Initialize the post processor."""
        # Compile regex patterns for efficiency
        self.compiled_patterns = [(re.compile(p, re.MULTILINE), r) for p, r in self.FORMATTING_PATTERNS]
        # Seed random number generator
        random.seed(int(time.time()))
    
    def process(self, text: str, emotion: str = "neutral", 
                add_greeting: bool = True, add_closing: bool = True) -> str:
        """Process the model output.
        
        Args:
            text: Raw model output
            emotion: Detected emotional state
            add_greeting: Whether to add an empathetic greeting
            add_closing: Whether to add a closing statement
            
        Returns:
            Processed text
        """
        start_time = time.time()
        
        # Normalize emotion
        if emotion not in self.GREETING_TEMPLATES:
            emotion = "neutral"
        
        # Skip empty or very short responses
        if not text or len(text.strip()) < 10:
            return text
        
        # Remove model signature if present
        text = self._remove_signature(text)
        
        # Add greeting if needed
        if add_greeting and not self._has_greeting(text):
            greeting = self._get_greeting(emotion)
            if greeting:
                text = greeting + text
        
        # Apply formatting improvements
        text = self._apply_formatting(text)
        
        # Add closing if needed
        if add_closing and not self._has_closing(text) and len(text) > 100:
            closing = self._get_closing(emotion)
            if closing:
                if not text.endswith("\n"):
                    text += "\n\n"
                text += closing
        
        # Log processing time
        processing_time = (time.time() - start_time) * 1000
        logger.debug(f"Post-processing completed in {processing_time:.2f} ms")
        
        return text
    
    def _remove_signature(self, text: str) -> str:
        """Remove model signature from text.
        
        Args:
            text: Text possibly containing signature
            
        Returns:
            Text without signature
        """
        # Common signature patterns
        signature_patterns = [
            r'\n\s*As an AI assistant.*?$',
            r'\n\s*I hope this helps.*?$',
            r'\n\s*Is there anything else.*?$',
            r'\n\s*Let me know if.*?$'
        ]
        
        result = text
        for pattern in signature_patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE | re.DOTALL)
        
        return result
    
    def _has_greeting(self, text: str) -> bool:
        """Check if text already has a greeting.
        
        Args:
            text: Text to check
            
        Returns:
            True if greeting already exists
        """
        # Check first 150 characters for common greetings
        first_part = text[:150].lower()
        
        greeting_indicators = [
            "i understand", "i see", "i appreciate", 
            "great question", "that's interesting",
            "i'd be happy", "i can help", "let me"
        ]
        
        return any(indicator in first_part for indicator in greeting_indicators)
    
    def _has_closing(self, text: str) -> bool:
        """Check if text already has a closing statement.
        
        Args:
            text: Text to check
            
        Returns:
            True if closing already exists
        """
        # Check last 200 characters for common closings
        last_part = text[-200:].lower()
        
        closing_indicators = [
            "hope this helps", "let me know", "is there anything else",
            "feel free to ask", "hope that", "further questions"
        ]
        
        return any(indicator in last_part for indicator in closing_indicators)
    
    def _get_greeting(self, emotion: str) -> str:
        """Get a random greeting template for the emotion.
        
        Args:
            emotion: Emotional state
            
        Returns:
            Greeting string
        """
        templates = self.GREETING_TEMPLATES.get(emotion, self.GREETING_TEMPLATES["neutral"])
        return random.choice(templates)
    
    def _get_closing(self, emotion: str) -> str:
        """Get a random closing template for the emotion.
        
        Args:
            emotion: Emotional state
            
        Returns:
            Closing string
        """
        templates = self.CLOSING_TEMPLATES.get(emotion, self.CLOSING_TEMPLATES["neutral"])
        return random.choice(templates)
    
    def _apply_formatting(self, text: str) -> str:
        """Apply formatting improvements.
        
        Args:
            text: Raw text
            
        Returns:
            Formatted text
        """
        result = text
        
        # Apply regex patterns
        for pattern, replacement in self.compiled_patterns:
            result = pattern.sub(replacement, result)
        
        # Fix potential Markdown formatting issues
        result = self._fix_markdown(result)
        
        return result
    
    def _fix_markdown(self, text: str) -> str:
        """Fix common Markdown formatting issues.
        
        Args:
            text: Text with potential Markdown issues
            
        Returns:
            Fixed text
        """
        result = text
        
        # Ensure code blocks have the right syntax
        # Replace ```code``` with ```\ncode\n```
        result = re.sub(r'```([^`\n]+)```', r'```\n\1\n```', result)
        
        # Ensure lists have a newline before them
        result = re.sub(r'([^\n])\n\* ', r'\1\n\n* ', result)
        
        # Ensure proper bold/italic formatting
        result = re.sub(r'\*\*([^*\n]+)\*\*', r'**\1**', result)
        result = re.sub(r'\*([^*\n]+)\*', r'*\1*', result)
        
        return result
