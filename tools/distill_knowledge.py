#!/usr/bin/env python3
import os
import sys
import json
import time
import sqlite3
import logging
import argparse
import requests
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("distill_knowledge.log")]
)
logger = logging.getLogger("knowledge_distiller")

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
BATCH_SIZE = 10
DEFAULT_TIMEOUT = 120  # seconds

class KnowledgeDistiller:
    """Connect to Premium AI API and generate SOP style Q&A knowledge."""
    
    def __init__(self, api_key: str, api_url: str, db_path: str, threads: int = 4):
        """Initialize the knowledge distiller.
        
        Args:
            api_key: API key for the premium AI service
            api_url: URL endpoint for the premium AI service
            db_path: Path to SQLite database file
            threads: Number of parallel threads for processing
        """
        self.api_key = api_key
        self.api_url = api_url
        self.db_path = db_path
        self.threads = threads
        self.ensure_db_exists()
        
    def ensure_db_exists(self) -> None:
        """Create the knowledge database with FTS5 if it doesn't exist."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create tables if they don't exist
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_metadata (
                id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL,
                subtopic TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Create FTS5 table with porter tokenizer for better search
            cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_content USING fts5(
                id UNINDEXED,  
                question,
                answer,
                keywords,
                content='',
                tokenize='porter unicode61'
            )
            ''')
            
            # Create a trigger to maintain the FTS index
            cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS knowledge_content_ai AFTER INSERT ON knowledge_metadata BEGIN
                INSERT INTO knowledge_content(id, question, answer, keywords)
                VALUES (new.id, '', '', '');
            END
            ''')
            
            conn.commit()
            logger.info("Database initialized successfully")
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def query_premium_ai(self, topic: str, subtopic: Optional[str] = None, 
                         retries: int = MAX_RETRIES) -> Dict[str, Any]:
        """Query the premium AI API for knowledge on a specific topic.
        
        Args:
            topic: The main topic to query
            subtopic: Optional subtopic for more specific knowledge
            retries: Number of retry attempts
            
        Returns:
            Dictionary containing the AI response
        """
        prompt = self._create_knowledge_prompt(topic, subtopic)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "gpt-4-turbo",  # Can be parameterized
            "messages": [
                {"role": "system", "content": "You are a professional knowledge base creator. Generate factual, accurate information in a Q&A format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # Low temperature for factual responses
            "response_format": {"type": "json_object"}
        }
        
        attempt = 0
        while attempt < retries:
            try:
                response = requests.post(
                    self.api_url, 
                    headers=headers, 
                    json=payload,
                    timeout=DEFAULT_TIMEOUT
                )
                response.raise_for_status()
                
                # Validate the response structure
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    try:
                        # Parse the JSON content from the response
                        content = data["choices"][0]["message"]["content"]
                        result = json.loads(content)
                        # Basic validation of the expected structure
                        if not isinstance(result, dict) or "qa_pairs" not in result:
                            raise ValueError("Invalid response format: missing 'qa_pairs' field")
                        return result
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse response as JSON: {e}")
                        raise
                else:
                    raise ValueError("Unexpected API response format")
                
            except (requests.RequestException, ValueError) as e:
                attempt += 1
                logger.warning(f"API request failed (attempt {attempt}/{retries}): {str(e)}")
                if attempt < retries:
                    time.sleep(RETRY_DELAY * attempt)  # Exponential backoff
                else:
                    logger.error(f"Maximum retries reached for topic '{topic}', subtopic '{subtopic}'")
                    raise
        
        # Should not reach here due to the raise in the else block above
        raise RuntimeError("Unexpected error in query_premium_ai")
    
    def _create_knowledge_prompt(self, topic: str, subtopic: Optional[str] = None) -> str:
        """Create a prompt for knowledge distillation.
        
        Args:
            topic: Main topic for knowledge
            subtopic: Optional subtopic
            
        Returns:
            Formatted prompt string
        """
        base_prompt = (
            f"Create a comprehensive knowledge base about {topic}"
            f"{f' focusing on {subtopic}' if subtopic else ''}."
            f"\n\nGenerate 5-10 question and answer pairs that cover important aspects of this topic."
            f"\n\nFor each Q&A pair:"
            f"\n- Make questions clear and specific"
            f"\n- Provide factual, accurate answers"
            f"\n- Include relevant technical details where appropriate"
            f"\n- Add 3-5 keywords for each Q&A pair"
            f"\n\nFormat your response as a JSON object with this structure:"
            f"\n{{\"qa_pairs\": [{{"
            f"\n  \"question\": \"What is X?\","
            f"\n  \"answer\": \"X is...\","
            f"\n  \"keywords\": \"term1, term2, term3\""
            f"\n}}, ... ]}}"
        )
        return base_prompt
    
    def store_knowledge(self, topic: str, subtopic: Optional[str], 
                         qa_pairs: List[Dict[str, str]], source: str = "premium_ai") -> None:
        """Store Q&A pairs in the SQLite database.
        
        Args:
            topic: Main knowledge topic
            subtopic: Optional subtopic
            qa_pairs: List of Q&A pairs with keywords
            source: Source of the knowledge
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            for qa_pair in qa_pairs:
                # First insert metadata to get an ID
                cursor.execute(
                    "INSERT INTO knowledge_metadata (topic, subtopic, source) VALUES (?, ?, ?)",
                    (topic, subtopic or "", source)
                )
                entry_id = cursor.lastrowid
                
                # Then insert the content with the same ID into FTS table
                cursor.execute(
                    "INSERT INTO knowledge_content (id, question, answer, keywords) VALUES (?, ?, ?, ?)",
                    (entry_id, qa_pair["question"], qa_pair["answer"], qa_pair["keywords"])
                )
            
            conn.commit()
            logger.info(f"Stored {len(qa_pairs)} Q&A pairs for topic '{topic}', subtopic '{subtopic or 'None'}'")
        except sqlite3.Error as e:
            logger.error(f"Database error while storing knowledge: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def process_topic(self, topic_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single topic to generate and store knowledge.
        
        Args:
            topic_info: Dictionary containing topic and optional subtopic
            
        Returns:
            Result dictionary with status and metadata
        """
        topic = topic_info["topic"]
        subtopic = topic_info.get("subtopic")
        source = topic_info.get("source", "premium_ai")
        
        try:
            result = self.query_premium_ai(topic, subtopic)
            qa_pairs = result.get("qa_pairs", [])
            
            if not qa_pairs:
                return {
                    "topic": topic,
                    "subtopic": subtopic,
                    "status": "failed",
                    "reason": "No Q&A pairs generated",
                    "count": 0
                }
            
            self.store_knowledge(topic, subtopic, qa_pairs, source)
            
            return {
                "topic": topic,
                "subtopic": subtopic,
                "status": "success",
                "count": len(qa_pairs)
            }
            
        except Exception as e:
            logger.error(f"Error processing topic '{topic}', subtopic '{subtopic}': {str(e)}")
            return {
                "topic": topic,
                "subtopic": subtopic,
                "status": "failed",
                "reason": str(e),
                "count": 0
            }
    
    def batch_process(self, topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process multiple topics in parallel.
        
        Args:
            topics: List of topic dictionaries
            
        Returns:
            List of result dictionaries
        """
        results = []
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_to_topic = {executor.submit(self.process_topic, topic): topic for topic in topics}
            
            for future in as_completed(future_to_topic):
                results.append(future.result())
        
        return results
    
    def process_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Process topics from a JSON file.
        
        Args:
            file_path: Path to JSON file with topics
            
        Returns:
            List of result dictionaries
        """
        try:
            with open(file_path, 'r') as f:
                topics = json.load(f)
                
            if not isinstance(topics, list):
                raise ValueError("File must contain a JSON array of topic objects")
                
            return self.batch_process(topics)
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
            raise

def main():
    parser = argparse.ArgumentParser(description="Distill knowledge from premium AI APIs into SQLite database")
    parser.add_argument("--api-key", help="API key for the premium AI service")
    parser.add_argument("--api-url", default="https://api.openai.com/v1/chat/completions", help="API endpoint URL")
    parser.add_argument("--db-path", default="knowledge.db", help="Path to SQLite database file")
    parser.add_argument("--topics-file", help="JSON file containing topics to process")
    parser.add_argument("--topic", help="Single topic to process")
    parser.add_argument("--subtopic", help="Subtopic for the single topic")
    parser.add_argument("--threads", type=int, default=4, help="Number of parallel threads")
    parser.add_argument("--mock", action="store_true", help="Use mock API for testing")
    args = parser.parse_args()
    
    # Get API key from environment if not provided
    api_key = args.api_key or os.environ.get("PREMIUM_AI_API_KEY")
    if not api_key and not args.mock:
        logger.error("API key must be provided via --api-key or PREMIUM_AI_API_KEY environment variable")
        sys.exit(1)
    
    # Initialize the distiller
    distiller = KnowledgeDistiller(
        api_key=api_key,
        api_url=args.api_url,
        db_path=args.db_path,
        threads=args.threads
    )
    
    # Process based on input arguments
    if args.topics_file:
        logger.info(f"Processing topics from file: {args.topics_file}")
        results = distiller.process_from_file(args.topics_file)
        
        success = sum(1 for r in results if r["status"] == "success")
        failed = len(results) - success
        logger.info(f"Completed processing {len(results)} topics: {success} successful, {failed} failed")
        
    elif args.topic:
        logger.info(f"Processing single topic: {args.topic}")
        result = distiller.process_topic({"topic": args.topic, "subtopic": args.subtopic})
        
        if result["status"] == "success":
            logger.info(f"Successfully processed topic: {args.topic}")
        else:
            logger.error(f"Failed to process topic: {args.topic}, reason: {result.get('reason')}")
            
    else:
        logger.error("Either --topics-file or --topic must be specified")
        sys.exit(1)

if __name__ == "__main__":
    main()
