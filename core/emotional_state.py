#!/usr/bin/env python3
import re
import logging
from typing import Dict, List, Tuple, Optional, Set

logger = logging.getLogger(__name__)

class EmotionalStateClassifier:
    """Lightweight emotional classifier using regex and heuristics only."""
    
    # Emotional states
    STATES = {
        "neutral": 0,
        "concerned": 1,
        "celebratory": 2,
        "frustrated": 3,
        "curious": 4
    }
    
    # Regex patterns for different emotional states
    PATTERNS = {
        "concerned": [
            r"\b(?:worried|concerned|anxious|afraid|scared|nervous|terrified|uneasy|distressed)\b",
            r"\b(?:problem|issue|trouble|difficult|challenging|hard|complex)\b",
            r"\b(?:help|assist|support|aid|guidance|advice)\b",
            r"\?{2,}",  # Multiple question marks
            r"\b(?:error|failure|crash|bug|glitch|broken|not working)\b"
        ],
        "celebratory": [
            r"\b(?:happy|excited|thrilled|delighted|pleased|glad|joy|celebrate|awesome|amazing|excellent)\b",
            r"\b(?:success|achievement|accomplished|completed|finished|solved)\b",
            r"\b(?:congratulations|congrats|cheers|hurray|yay)\b",
            r"!{2,}",  # Multiple exclamation marks
            r"\b(?:thank you|thanks|appreciate|grateful)\b"
        ],
        "frustrated": [
            r"\b(?:frustrated|annoyed|angry|mad|upset|irritated|furious|fed up)\b",
            r"\b(?:can't|cannot|won't|will not|never|impossible)\b",
            r"\b(?:terrible|horrible|awful|bad|worst|sucks|poor|disappointed)\b",
            r"!+\?+|@#\$%",  # Mixed punctuation or symbols indicating frustration
            r"\b(?:wasted|lost|ruined|failed|stupid|useless|worthless)\b"
        ],
        "curious": [
            r"\b(?:curious|interested|wonder|wondering|want to know|tell me about|explain|how does|what is)\b",
            r"\b(?:learning|discover|exploration|research|study|understand|knowledge)\b",
            r"\b(?:example|instance|case|scenario|sample)\b",
            r"\?",  # Question mark
            r"\b(?:difference between|compare|versus|vs)\b"
        ]
    }
    
    # Keywords that override other emotions
    OVERRIDE_KEYWORDS = {
        "urgent": "concerned",
        "emergency": "concerned",
        "critical": "concerned", 
        "congratulations": "celebratory",
        "help me": "concerned",
        "frustrated": "frustrated",
        "curious": "curious"
    }
    
    # Modifier templates for different emotional states
    STATE_MODIFIERS = {
        "neutral": "Respond in a balanced and informative way.",
        "concerned": "Respond calmly and reassuringly. Acknowledge concerns and provide clear guidance.",
        "celebratory": "Respond with enthusiasm and positivity. Share in the excitement while remaining professional.",
        "frustrated": "Respond with patience and empathy. Acknowledge frustration and focus on solutions.",
        "curious": "Respond with detailed explanations. Satisfy curiosity with comprehensive information."
    }
    
    def __init__(self):
        """Initialize the emotional state classifier."""
        # Compile regex patterns for efficiency
        self.compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for state, patterns in self.PATTERNS.items():
            self.compiled_patterns[state] = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    
    def detect_emotion(self, text: str) -> Tuple[str, float]:
        """Detect the emotional state from text.
        
        Args:
            text: Input text
            
        Returns:
            Tuple of (emotional_state, confidence_score)
        """
        # Initial state is neutral with zero score
        scores: Dict[str, float] = {state: 0.0 for state in self.STATES}
        
        # Check for override keywords first
        for keyword, emotion in self.OVERRIDE_KEYWORDS.items():
            if re.search(r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE):
                logger.debug(f"Override keyword detected: {keyword} -> {emotion}")
                return emotion, 0.9  # High confidence for override keywords
        
        # Apply regex patterns
        for state, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    # Increase score based on number of matches
                    match_score = min(len(matches) * 0.2, 0.6)  # Cap at 0.6
                    scores[state] += match_score
                    
                    # Additional score for matches near the beginning or end
                    first_50_chars = text[:50].lower()
                    last_50_chars = text[-50:].lower()
                    for match in matches:
                        match_lower = match.lower()
                        if match_lower in first_50_chars or match_lower in last_50_chars:
                            scores[state] += 0.1
        
        # Apply length heuristics
        if "?" in text:
            question_count = text.count("?")
            if question_count > 3:
                scores["concerned"] += 0.3
            elif question_count > 0:
                scores["curious"] += 0.3
        
        if "!" in text:
            exclamation_count = text.count("!")
            if exclamation_count > 3:
                scores["frustrated"] += 0.3
                scores["celebratory"] += 0.2
        
        # Normalize scores
        total_score = sum(scores.values())
        if total_score > 0:
            scores = {k: v / total_score for k, v in scores.items()}
        
        # Get the highest scoring state
        max_state = max(scores.items(), key=lambda x: x[1])
        
        # If highest score is too low, default to neutral
        if max_state[1] < 0.4:
            return "neutral", 0.8
        
        return max_state[0], max_state[1]
    
    def get_persona_modifier(self, text: str, include_confidence: bool = False) -> str:
        """Get the persona modifier for the detected emotional state.
        
        Args:
            text: Input text
            include_confidence: Whether to include confidence in the modifier
            
        Returns:
            Persona modifier string
        """
        emotion, confidence = self.detect_emotion(text)
        modifier = self.STATE_MODIFIERS.get(emotion, self.STATE_MODIFIERS["neutral"])
        
        if include_confidence and confidence < 0.6:
            # For low confidence, blend with neutral
            neutral_modifier = self.STATE_MODIFIERS["neutral"]
            return f"{modifier} {neutral_modifier}"
        
        return modifier
    
    def analyze_conversation(self, messages: List[Dict[str, str]]) -> str:
        """Analyze a conversation to detect overall emotional state.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Returns:
            Persona modifier string based on emotional state
        """
        # Extract user messages
        user_messages = [msg["content"] for msg in messages if msg["role"] == "user"]
        
        # If no user messages, return neutral
        if not user_messages:
            return self.STATE_MODIFIERS["neutral"]
        
        # Give more weight to recent messages
        if len(user_messages) > 2:
            recent_message = user_messages[-1]
            previous_message = " ".join(user_messages[-3:-1])
            
            # Detect emotion in the most recent message
            recent_emotion, recent_confidence = self.detect_emotion(recent_message)
            
            # If recent emotion is strong, prioritize it
            if recent_confidence > 0.7:
                return self.STATE_MODIFIERS[recent_emotion]
            
            # Otherwise, analyze both recent and previous messages
            previous_emotion, previous_confidence = self.detect_emotion(previous_message)
            
            # If emotions match, strengthen the confidence
            if recent_emotion == previous_emotion and recent_emotion != "neutral":
                return self.STATE_MODIFIERS[recent_emotion]
            
            # If different, prioritize the recent emotion unless it's neutral
            if recent_emotion != "neutral":
                return self.STATE_MODIFIERS[recent_emotion]
            else:
                return self.STATE_MODIFIERS[previous_emotion]
        
        # For shorter conversations, just analyze the latest message
        latest_message = user_messages[-1]
        emotion, _ = self.detect_emotion(latest_message)
        return self.STATE_MODIFIERS[emotion]
