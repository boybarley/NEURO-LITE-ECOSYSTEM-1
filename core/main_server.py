#!/usr/bin/env python3
import os
import re
import json
import time
import uuid
import asyncio
import logging
import argparse
import threading
import traceback
from typing import Dict, List, Any, Optional, Set, Union, AsyncGenerator
from pathlib import Path
from functools import lru_cache
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Local imports
from llama_cpp_adapter import LlamaCppAdapter
from emotional_state import EmotionalStateClassifier
from rag_engine import RAGEngine
from context_manager import ContextManager
from post_processor import PostProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("neuro-lite.log")
    ]
)
logger = logging.getLogger("neuro-lite")

# Load configuration
def load_config() -> Dict[str, Any]:
    """Load configuration from environment or config file."""
    config_path = os.environ.get("CONFIG_PATH", "config.env")
    config = {
        "SERVER_HOST": "0.0.0.0",
        "SERVER_PORT": 8000,
        "LOG_LEVEL": "INFO",
        "MAX_CONNECTIONS": 10,
        "MODEL_PATH": "/opt/neuro-lite/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "CONTEXT_LENGTH": 4096,
        "SYSTEM_PROMPT": "You are a helpful AI assistant. You answer questions accurately, professionally, and with appropriate tone.",
        "DB_PATH": "/opt/neuro-lite/data/knowledge.db",
        "ENABLE_AUTH": False,
        "AUTH_TOKEN": "",
        "THREADS": min(os.cpu_count() or 4, 4),  # Use max 4 threads
        "BATCH_SIZE": 512
    }
    
    # Try to read from config file
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line.startswith("#") or not line:
                        continue
                    # Parse key-value pairs
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"\'')
                        config[key] = value
        except Exception as e:
            logger.warning(f"Failed to parse config file {config_path}: {e}")
    
    # Convert numeric values
    for key in ["SERVER_PORT", "MAX_CONNECTIONS", "CONTEXT_LENGTH", "THREADS", "BATCH_SIZE"]:
        if key in config:
            try:
                config[key] = int(config[key])
            except (ValueError, TypeError):
                logger.warning(f"Invalid {key} value: {config[key]}, using default")
    
    # Convert boolean values
    for key in ["ENABLE_AUTH"]:
        if key in config:
            config[key] = str(config[key]).lower() in ["true", "yes", "1", "t", "y"]
    
    return config

# Load configuration
CONFIG = load_config()

# Set log level
log_level = getattr(logging, CONFIG["LOG_LEVEL"].upper(), logging.INFO)
logging.getLogger().setLevel(log_level)
logger.setLevel(log_level)

# Initialize components
def init_components():
    """Initialize all components."""
    # Initialize llama.cpp adapter
    model = LlamaCppAdapter(
        model_path=CONFIG["MODEL_PATH"],
        n_threads=CONFIG["THREADS"],
        n_ctx=CONFIG["CONTEXT_LENGTH"],
        n_batch=CONFIG["BATCH_SIZE"]
    )
    
    # Initialize emotional state classifier
    emotion_classifier = EmotionalStateClassifier()
    
    # Initialize RAG engine
    rag_engine = RAGEngine(db_path=CONFIG["DB_PATH"])
    
    # Initialize post processor
    post_processor = PostProcessor()
    
    return model, emotion_classifier, rag_engine, post_processor

MODEL, EMOTION_CLASSIFIER, RAG_ENGINE, POST_PROCESSOR = init_components()

# Create FastAPI app
app = FastAPI(
    title="Neuro-Lite",
    description="A lightweight conversational AI system",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Active conversations
active_conversations: Dict[str, ContextManager] = {}
conversation_locks: Dict[str, threading.RLock] = {}
cleanup_timer = None

# Create a thread pool for CPU-bound tasks
thread_pool = ThreadPoolExecutor(max_workers=CONFIG["THREADS"])

# Request models
class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(None, description="Conversation ID")
    message: str = Field(..., description="User message")
    stream: bool = Field(True, description="Whether to stream the response")
    system_prompt: Optional[str] = Field(None, description="Custom system prompt")

class ResetRequest(BaseModel):
    conversation_id: str = Field(..., description="Conversation ID to reset")

# Response models
class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    created_at: str
    processing_time: float

# Mount static files
webui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui")
static_dir = os.path.join(webui_dir, "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=webui_dir)

# Utility functions
def get_or_create_conversation(conversation_id: Optional[str] = None, 
                              system_prompt: Optional[str] = None) -> Tuple[str, ContextManager]:
    """Get or create a conversation context.
    
    Args:
        conversation_id: Optional existing conversation ID
        system_prompt: Optional custom system prompt
        
    Returns:
        Tuple of (conversation_id, context_manager)
    """
    if conversation_id and conversation_id in active_conversations:
        return conversation_id, active_conversations[conversation_id]
    
    # Create new conversation
    new_id = conversation_id or str(uuid.uuid4())
    system_prompt = system_prompt or CONFIG["SYSTEM_PROMPT"]
    
    context = ContextManager(system_prompt=system_prompt)
    active_conversations[new_id] = context
    conversation_locks[new_id] = threading.RLock()
    
    logger.info(f"Created new conversation: {new_id}")
    return new_id, context

def cleanup_old_conversations():
    """Clean up old conversations to free memory."""
    # Runs as a background task
    while True:
        time.sleep(300)  # Check every 5 minutes
        try:
            now = time.time()
            to_remove = []
            
            # Use a copy of keys to avoid modification during iteration
            for conv_id in list(active_conversations.keys()):
                # If conversation hasn't been accessed in 2 hours, remove it
                if conv_id in conversation_locks:
                    lock = conversation_locks[conv_id]
                    if lock.acquire(blocking=False):
                        try:
                            # Remove old conversation
                            to_remove.append(conv_id)
                        finally:
                            lock.release()
            
            # Remove old conversations
            for conv_id in to_remove:
                del active_conversations[conv_id]
                del conversation_locks[conv_id]
                logger.info(f"Cleaned up old conversation: {conv_id}")
        
        except Exception as e:
            logger.error(f"Error in cleanup task: {str(e)}")

# Start cleanup task
def start_cleanup_task():
    global cleanup_timer
    cleanup_timer = threading.Thread(target=cleanup_old_conversations, daemon=True)
    cleanup_timer.start()

# API routes
@app.get("/")
async def root(request: Request):
    """Serve the web UI."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """Process a chat message and return a complete response."""
    start_time = time.time()
    
    # Get or create conversation
    conversation_id, context = get_or_create_conversation(
        request.conversation_id, 
        request.system_prompt
    )
    
    # Get lock for this conversation
    lock = conversation_locks[conversation_id]
    
    # Process message
    try:
        with lock:
            # Add user message to context
            context.add_message("user", request.message)
            
            # Detect emotional state
            emotion = EMOTION_CLASSIFIER.detect_emotion(request.message)[0]
            
            # Get persona modifier based on emotion
            persona_modifier = EMOTION_CLASSIFIER.get_persona_modifier(request.message)
            
            # Get relevant knowledge if available
            knowledge, source = RAG_ENGINE.get_most_relevant_passage(request.message)
            
            # Prepare prompt with context
            messages = context.get_context()
            
            # Add persona modifier and knowledge if available
            system_messages = [m for m in messages if m["role"] == "system"]
            if system_messages:
                # Update the first system message
                system_messages[0]["content"] += f"\n\n{persona_modifier}"
                
                if knowledge:
                    system_messages[0]["content"] += f"\n\nRelevant information:\n{knowledge}"
            
            # Generate response (non-streaming)
            response = MODEL.generate(
                prompt=request.message,
                system_prompt=messages[0]["content"] if messages else None,
                max_tokens=512,
                temperature=0.7,
                stream=False
            )
            
            # Process response to improve it
            processed_response = POST_PROCESSOR.process(
                text=response,
                emotion=emotion,
                add_greeting=True,
                add_closing=True
            )
            
            # Add to context
            context.add_message("assistant", processed_response)
            
            processing_time = time.time() - start_time
            
            return {
                "conversation_id": conversation_id,
                "message": processed_response,
                "created_at": datetime.now().isoformat(),
                "processing_time": processing_time
            }
    
    except Exception as e:
        logger.error(f"Error processing chat: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream a chat response."""
    # Get or create conversation
    conversation_id, context = get_or_create_conversation(
        request.conversation_id, 
        request.system_prompt
    )
    
    # Get lock for this conversation
    lock = conversation_locks[conversation_id]
    
    # Create response headers
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    
    async def stream_generator() -> AsyncGenerator[str, None]:
        """Generate streaming response."""
        try:
            # Acquire lock
            if not lock.acquire(blocking=False):
                # If can't get lock, someone else is processing this conversation
                yield f"data: {json.dumps({'type': 'error', 'error': 'Conversation is being processed by another request'})}\n\n"
                return
            
            try:
                # Add user message to context
                context.add_message("user", request.message)
                
                # Detect emotional state
                emotion = EMOTION_CLASSIFIER.detect_emotion(request.message)[0]
                
                # Get persona modifier based on emotion
                persona_modifier = EMOTION_CLASSIFIER.get_persona_modifier(request.message)
                
                # Get relevant knowledge if available
                knowledge, source = RAG_ENGINE.get_most_relevant_passage(request.message)
                
                # Prepare prompt with context
                messages = context.get_context()
                
                # Add persona modifier and knowledge if available
                system_messages = [m for m in messages if m["role"] == "system"]
                if system_messages:
                    # Update the first system message
                    system_messages[0]["content"] += f"\n\n{persona_modifier}"
                    
                    if knowledge:
                        system_messages[0]["content"] += f"\n\nRelevant information:\n{knowledge}"
                
                # Send initial SSE message with conversation ID
                yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id})}\n\n"
                
                # Generate streaming response
                full_response = ""
                first_token = True
                async_gen = MODEL.generate(
                    prompt=request.message,
                    system_prompt=messages[0]["content"] if messages else None,
                    max_tokens=512,
                    temperature=0.7,
                    stream=True
                )
                
                # Adapt to both synchronous and asynchronous generators
                if hasattr(async_gen, "__aiter__"):
                    async for token in async_gen:
                        full_response += token
                        # Stream the token
                        yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
                        # Small delay to prevent overwhelming the client
                        if first_token:
                            first_token = False
                            await asyncio.sleep(0.01)
                else:
                    # Fallback for synchronous generator
                    for token in async_gen:
                        full_response += token
                        # Stream the token
                        yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
                        # Small delay to prevent overwhelming the client
                        if first_token:
                            first_token = False
                            await asyncio.sleep(0.01)
                
                # Process complete response for better formatting
                processed_response = POST_PROCESSOR.process(
                    text=full_response,
                    emotion=emotion,
                    add_greeting=True,
                    add_closing=True
                )
                
                # Add to context
                context.add_message("assistant", processed_response)
                
                # Send done message with final processed response
                yield f"data: {json.dumps({'type': 'end', 'message': processed_response})}\n\n"
            
            finally:
                # Always release lock
                lock.release()
        
        except Exception as e:
            logger.error(f"Error streaming response: {str(e)}")
            logger.error(traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(
        stream_generator(),
        headers=headers
    )

@app.post("/api/conversations/reset")
async def reset_conversation(request: ResetRequest):
    """Reset a conversation to start fresh."""
    if request.conversation_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get lock for this conversation
    lock = conversation_locks[request.conversation_id]
    
    try:
        with lock:
            # Clear history but keep the conversation
            active_conversations[request.conversation_id].clear_history()
            return {"status": "success", "message": "Conversation reset successfully"}
    except Exception as e:
        logger.error(f"Error resetting conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "active_conversations": len(active_conversations),
        "model": os.path.basename(CONFIG["MODEL_PATH"]),
        "uptime": time.time() - start_time
    }

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    global start_time
    start_time = time.time()
    
    # Start cleanup task
    start_cleanup_task()
    
    logger.info("Neuro-Lite server started")
    logger.info(f"Model: {CONFIG['MODEL_PATH']}")
    logger.info(f"Threads: {CONFIG['THREADS']}")
    logger.info(f"DB Path: {CONFIG['DB_PATH']}")

@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    # Close RAG engine
    RAG_ENGINE.close()
    
    # Unload model
    MODEL.unload_model()
    
    logger.info("Neuro-Lite server shutdown")

# Main entry point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Neuro-Lite Server")
    parser.add_argument("--host", help="Host to bind", default=CONFIG["SERVER_HOST"])
    parser.add_argument("--port", type=int, help="Port to bind", default=CONFIG["SERVER_PORT"])
    args = parser.parse_args()
    
    # Start the server
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port,
        log_level=CONFIG["LOG_LEVEL"].lower()
    )
