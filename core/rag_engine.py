#!/usr/bin/env python3
import os
import re
import time
import sqlite3
import logging
import threading
import aiosqlite
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class RAGEngine:
    """Retrieval Augmented Generation engine using SQLite FTS5."""
    
    def __init__(self, db_path: str, pool_size: int = 3):
        """Initialize the RAG engine.
        
        Args:
            db_path: Path to the SQLite database
            pool_size: Size of the connection pool
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._conn_pool: List[Optional[sqlite3.Connection]] = [None] * pool_size
        self._pool_locks = [threading.Lock() for _ in range(pool_size)]
        self._pool_in_use = [False] * pool_size
        self._init_lock = threading.Lock()
        
        # Initialize the database
        self._initialize_db()
    
    def _initialize_db(self) -> None:
        """Initialize the database, creating tables if they don't exist."""
        if not os.path.exists(self.db_path):
            logger.warning(f"Database file not found: {self.db_path}")
            self._create_empty_db()
            return
        
        try:
            # Test connection and check schema
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if tables exist
                tables_query = "SELECT name FROM sqlite_master WHERE type='table'"
                tables = [row[0] for row in cursor.execute(tables_query).fetchall()]
                
                if "knowledge_content" not in tables:
                    logger.warning("Required tables not found in database, initializing empty tables")
                    self._create_empty_db()
                    return
                    
                # Enable WAL mode for better performance
                cursor.execute("PRAGMA journal_mode=WAL")
                
                # Get row count
                count_query = "SELECT COUNT(*) FROM knowledge_content"
                count = cursor.execute(count_query).fetchone()[0]
                
                logger.info(f"Database initialized with {count} knowledge entries")
                
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            logger.warning("Creating empty database")
            self._create_empty_db()
    
    def _create_empty_db(self) -> None:
        """Create an empty database with required tables."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create metadata table
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
                
                # Create FTS5 table
                cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_content USING fts5(
                    id UNINDEXED,  
                    question,
                    answer,
                    keywords,
                    content=''
                )
                ''')
                
                # Enable WAL mode for better performance
                cursor.execute("PRAGMA journal_mode=WAL")
                
                # Add a few fallback entries
                fallback_entries = [
                    {
                        "topic": "general",
                        "subtopic": "introduction",
                        "question": "What is Neuro-Lite?",
                        "answer": "Neuro-Lite is a lightweight conversational AI system designed to run on low-resource hardware. It provides helpful responses while being efficient with memory and CPU usage.",
                        "keywords": "neuro-lite, AI, introduction, system"
                    },
                    {
                        "topic": "system",
                        "subtopic": "capabilities",
                        "question": "What can Neuro-Lite do?",
                        "answer": "Neuro-Lite can answer questions, provide information on topics in its knowledge base, and engage in helpful conversation. It's designed to be efficient and responsive even on limited hardware.",
                        "keywords": "capabilities, features, functionality"
                    },
                    {
                        "topic": "system",
                        "subtopic": "limitations",
                        "question": "What are the limitations of Neuro-Lite?",
                        "answer": "As a lightweight AI system, Neuro-Lite has some limitations: it can only answer based on its existing knowledge base, it doesn't connect to the internet, and it has been designed for efficiency rather than handling extremely complex reasoning tasks.",
                        "keywords": "limitations, constraints, capabilities"
                    }
                ]
                
                # Insert fallback entries
                for entry in fallback_entries:
                    # First insert metadata
                    cursor.execute(
                        "INSERT INTO knowledge_metadata (topic, subtopic, source) VALUES (?, ?, ?)",
                        (entry["topic"], entry["subtopic"], "system")
                    )
                    entry_id = cursor.lastrowid
                    
                    # Then insert content
                    cursor.execute(
                        "INSERT INTO knowledge_content (id, question, answer, keywords) VALUES (?, ?, ?, ?)",
                        (entry_id, entry["question"], entry["answer"], entry["keywords"])
                    )
                
                conn.commit()
                logger.info(f"Created empty database with {len(fallback_entries)} fallback entries")
                
        except sqlite3.Error as e:
            logger.error(f"Failed to create empty database: {e}")
            raise
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool.
        
        Returns:
            SQLite connection
        """
        # Try to get an existing connection
        for i in range(self.pool_size):
            with self._pool_locks[i]:
                if not self._pool_in_use[i]:
                    if self._conn_pool[i] is None:
                        self._conn_pool[i] = sqlite3.connect(self.db_path)
                        self._conn_pool[i].row_factory = sqlite3.Row
                    self._pool_in_use[i] = True
                    return self._conn_pool[i]
        
        # If all connections are in use, create a temporary one
        logger.warning("Connection pool exhausted, creating temporary connection")
        return sqlite3.connect(self.db_path)
    
    def _release_connection(self, conn: sqlite3.Connection) -> None:
        """Release a connection back to the pool.
        
        Args:
            conn: Connection to release
        """
        # Check if this is a pooled connection
        for i in range(self.pool_size):
            with self._pool_locks[i]:
                if self._conn_pool[i] is conn:
                    self._pool_in_use[i] = False
                    return
        
        # If not in the pool, it was a temporary connection - close it
        conn.close()
    
    async def search_async(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Search the knowledge base asynchronously.
        
        Args:
            query: Search query
            limit: Maximum number of results to return
            
        Returns:
            List of matching entries
        """
        if not query.strip():
            return []
        
        # Clean the query to make it safe for FTS
        clean_query = self._clean_query(query)
        
        try:
            # Use aiosqlite for async operation
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # First try an exact match with the query
                exact_search = f'"{clean_query}"'
                async with db.execute(
                    """
                    SELECT id, question, answer, keywords,
                           highlight(knowledge_content, 0, '<mark>', '</mark>') as highlighted_question,
                           highlight(knowledge_content, 1, '<mark>', '</mark>') as highlighted_answer,
                           rank
                    FROM knowledge_content
                    WHERE question MATCH ? OR answer MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (exact_search, exact_search, limit)
                ) as cursor:
                    exact_results = [dict(row) for row in await cursor.fetchall()]
                
                # If we got exact matches, return them
                if exact_results:
                    return exact_results
                
                # Otherwise, try a broader search
                search_terms = " OR ".join([term for term in clean_query.split() if len(term) > 2])
                if not search_terms:
                    search_terms = clean_query  # Fallback if no terms longer than 2 chars
                
                async with db.execute(
                    """
                    SELECT id, question, answer, keywords,
                           highlight(knowledge_content, 0, '<mark>', '</mark>') as highlighted_question,
                           highlight(knowledge_content, 1, '<mark>', '</mark>') as highlighted_answer,
                           rank
                    FROM knowledge_content
                    WHERE knowledge_content MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (search_terms, limit)
                ) as cursor:
                    results = [dict(row) for row in await cursor.fetchall()]
                
                return results
                
        except Exception as e:
            logger.error(f"Error in async search: {str(e)}")
            return []
    
    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Search the knowledge base synchronously.
        
        Args:
            query: Search query
            limit: Maximum number of results to return
            
        Returns:
            List of matching entries
        """
        if not query.strip():
            return []
        
        # Clean the query to make it safe for FTS
        clean_query = self._clean_query(query)
        
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # First try an exact match with the query
            exact_search = f'"{clean_query}"'
            cursor.execute(
                """
                SELECT id, question, answer, keywords,
                       highlight(knowledge_content, 0, '<mark>', '</mark>') as highlighted_question,
                       highlight(knowledge_content, 1, '<mark>', '</mark>') as highlighted_answer,
                       rank
                FROM knowledge_content
                WHERE question MATCH ? OR answer MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (exact_search, exact_search, limit)
            )
            exact_results = [dict(row) for row in cursor.fetchall()]
            
            # If we got exact matches, return them
            if exact_results:
                return exact_results
            
            # Otherwise, try a broader search
            search_terms = " OR ".join([term for term in clean_query.split() if len(term) > 2])
            if not search_terms:
                search_terms = clean_query  # Fallback if no terms longer than 2 chars
            
            cursor.execute(
                """
                SELECT id, question, answer, keywords,
                       highlight(knowledge_content, 0, '<mark>', '</mark>') as highlighted_question,
                       highlight(knowledge_content, 1, '<mark>', '</mark>') as highlighted_answer,
                       rank
                FROM knowledge_content
                WHERE knowledge_content MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (search_terms, limit)
            )
            results = [dict(row) for row in cursor.fetchall()]
            
            return results
            
        except sqlite3.Error as e:
            logger.error(f"Database search error: {str(e)}")
            return []
        finally:
            if conn:
                self._release_connection(conn)
    
    def _clean_query(self, query: str) -> str:
        """Clean a search query for safe use with FTS.
        
        Args:
            query: Raw search query
            
        Returns:
            Cleaned query
        """
        # Remove special characters and operators that might break FTS queries
        query = re.sub(r'["\'^:*-]', ' ', query)
        
        # Remove extra whitespace
        query = re.sub(r'\s+', ' ', query).strip()
        
        return query
    
    def get_most_relevant_passage(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Get the most relevant passage for a query.
        
        Args:
            query: Search query
            
        Returns:
            Tuple of (context_text, source_info)
        """
        results = self.search(query, limit=1)
        
        if not results:
            return None, None
        
        result = results[0]
        
        # Format the context passage
        context = f"Question: {result['question']}\nAnswer: {result['answer']}"
        source = f"Source ID: {result['id']}"
        
        return context, source
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """Get statistics about the knowledge base.
        
        Returns:
            Dictionary with statistics
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute("SELECT COUNT(*) FROM knowledge_content")
            total_count = cursor.fetchone()[0]
            
            # Get topics
            cursor.execute(
                """
                SELECT topic, COUNT(*) as count 
                FROM knowledge_metadata 
                GROUP BY topic 
                ORDER BY count DESC
                """
            )
            topics = [{"topic": row[0], "count": row[1]} for row in cursor.fetchall()]
            
            # Get most recent entries
            cursor.execute(
                """
                SELECT id, topic, subtopic, created_at 
                FROM knowledge_metadata 
                ORDER BY created_at DESC 
                LIMIT 5
                """
            )
            recent = [dict(row) for row in cursor.fetchall()]
            
            return {
                "total_entries": total_count,
                "topics": topics,
                "recent_entries": recent
            }
            
        except sqlite3.Error as e:
            logger.error(f"Database error getting stats: {str(e)}")
            return {"error": str(e)}
        finally:
            if conn:
                self._release_connection(conn)
    
    def close(self) -> None:
        """Close all database connections."""
        for i in range(self.pool_size):
            with self._pool_locks[i]:
                if self._conn_pool[i] is not None:
                    try:
                        self._conn_pool[i].close()
                    except sqlite3.Error:
                        pass
                    self._conn_pool[i] = None
                    self._pool_in_use[i] = False
