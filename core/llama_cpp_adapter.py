#!/usr/bin/env python3
import os
import time
import logging
import threading
from typing import List, Dict, Any, Optional, Generator, Union
from llama_cpp import Llama

logger = logging.getLogger(__name__)

class LlamaCppAdapter:
    """Singleton adapter for llama.cpp model to ensure memory efficiency."""
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LlamaCppAdapter, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, model_path: str, n_threads: Optional[int] = None, 
                 n_ctx: int = 4096, n_batch: int = 512):
        """Initialize the LlamaCpp adapter.
        
        Args:
            model_path: Path to the model file
            n_threads: Number of threads to use (default: number of CPU cores)
            n_ctx: Size of context window
            n_batch: Batch size for processing
        """
        with self._lock:
            if self._initialized:
                return
                
            self.model_path = model_path
            self.n_threads = n_threads or os.cpu_count() or 4
            self.n_ctx = n_ctx
            self.n_batch = n_batch
            self.model = None
            self._load_model()
            self._initialized = True
    
    def _load_model(self) -> None:
        """Load the model into memory."""
        if not os.path.exists(self.model_path):
            error_msg = f"Model file not found: {self.model_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        logger.info(f"Loading model: {self.model_path}")
        start_time = time.time()
        
        try:
            # Load the model with optimized settings
            self.model = Llama(
                model_path=self.model_path,
                n_threads=self.n_threads,
                n_ctx=self.n_ctx,
                n_batch=self.n_batch,
                verbose=False
            )
            
            load_time = time.time() - start_time
            logger.info(f"Model loaded successfully in {load_time:.2f} seconds")
            
        except Exception as e:
            error_msg = f"Failed to load model: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def generate(self, 
                prompt: str, 
                system_prompt: Optional[str] = None,
                max_tokens: int = 512, 
                temperature: float = 0.7,
                top_p: float = 0.9,
                stop: Optional[List[str]] = None,
                stream: bool = False) -> Union[str, Generator[str, None, None]]:
        """Generate a response from the model.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (higher = more random)
            top_p: Top-p sampling parameter
            stop: List of stop sequences
            stream: Whether to stream the response
            
        Returns:
            Either the full response string or a generator yielding tokens
        """
        with self._lock:
            if not self.model:
                self._load_model()
            
            # Basic parameters sanitization
            max_tokens = min(max(max_tokens, 16), self.n_ctx // 2)
            temperature = min(max(temperature, 0.0), 1.0)
            top_p = min(max(top_p, 0.0), 1.0)
            
            # Default stop sequences if none provided
            if stop is None:
                stop = ["\n\n", "</s>", "# "]
            
            # Build the messages array
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            # Generate in streaming mode
            if stream:
                return self._generate_streaming(messages, max_tokens, temperature, top_p, stop)
            
            # Generate complete response at once
            try:
                response = self.model.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop=stop,
                    stream=False
                )
                
                # Extract the assistant's response
                if "choices" in response and len(response["choices"]) > 0:
                    return response["choices"][0]["message"]["content"]
                
                return ""
                
            except Exception as e:
                logger.error(f"Error during generation: {str(e)}")
                return "I apologize, but I encountered an error while processing your request."
    
    def _generate_streaming(self, 
                           messages: List[Dict[str, str]], 
                           max_tokens: int,
                           temperature: float,
                           top_p: float,
                           stop: List[str]) -> Generator[str, None, None]:
        """Generate a streaming response.
        
        Args:
            messages: Chat messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Top-p sampling parameter
            stop: List of stop sequences
            
        Yields:
            Response tokens as they are generated
        """
        try:
            response_stream = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop,
                stream=True
            )
            
            for chunk in response_stream:
                if "choices" in chunk and len(chunk["choices"]) > 0:
                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                    if content:
                        yield content
        
        except Exception as e:
            logger.error(f"Error during streaming generation: {str(e)}")
            yield "I apologize, but I encountered an error while processing your request."
    
    def get_embedding(self, text: str) -> List[float]:
        """Get embeddings for the given text.
        
        Args:
            text: Input text
            
        Returns:
            Embedding vector
        """
        with self._lock:
            if not self.model:
                self._load_model()
            
            try:
                # Note: This is a simplification as llama.cpp's Python bindings
                # may not directly support embeddings. In a production system,
                # this would be implemented with the appropriate API call.
                embedding = self.model.create_embedding(
                    input=text,
                    model=os.path.basename(self.model_path)
                )
                
                if "data" in embedding and len(embedding["data"]) > 0:
                    return embedding["data"][0]["embedding"]
                
                return []
                
            except Exception as e:
                logger.error(f"Error generating embedding: {str(e)}")
                # Return an empty embedding on error
                return []
    
    def unload_model(self) -> None:
        """Unload the model from memory."""
        with self._lock:
            if self.model:
                logger.info("Unloading model from memory")
                self.model = None
