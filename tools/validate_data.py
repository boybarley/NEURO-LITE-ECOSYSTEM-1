#!/usr/bin/env python3
import os
import re
import sys
import json
import hashlib
import logging
import argparse
import sqlite3
from typing import Dict, List, Set, Tuple, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("data_validation.log")]
)
logger = logging.getLogger("data_validator")

class DataValidator:
    """Validates crowdsourced data for safety and quality."""
    
    # Regex patterns for PII detection
    PII_PATTERNS = {
        'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        'phone': re.compile(r'\b(\+\d{1,3}[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'),
        'ssn': re.compile(r'\b\d{3}[-]?\d{2}[-]?\d{4}\b'),
        'credit_card': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{16}\b'),
        'ip_address': re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
        'url': re.compile(r'\bhttps?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+\b'),
    }
    
    # Toxic language patterns
    TOXIC_WORDS = set([
        # This is a minimal set - would be expanded in a real implementation
        'fuck', 'shit', 'ass', 'bitch', 'damn', 'cunt', 'dick', 'cock', 'pussy',
        'nigger', 'nigga', 'faggot', 'retard', 'whore', 'slut'
    ])
    
    def __init__(self, db_path: Optional[str] = None, max_workers: int = 4):
        """Initialize the data validator.
        
        Args:
            db_path: Optional path to SQLite database to check for duplicates
            max_workers: Maximum number of parallel workers
        """
        self.db_path = db_path
        self.max_workers = max_workers
        self.seen_hashes: Set[str] = set()
        self.conn = None
        
        if db_path and os.path.exists(db_path):
            try:
                self.conn = sqlite3.connect(db_path)
                self.load_existing_hashes()
            except sqlite3.Error as e:
                logger.warning(f"Could not connect to database for duplicate checking: {e}")
    
    def __del__(self):
        """Clean up database connection on object destruction."""
        if self.conn:
            self.conn.close()
    
    def load_existing_hashes(self) -> None:
        """Load existing content hashes from database to detect duplicates."""
        if not self.conn:
            return
            
        try:
            cursor = self.conn.cursor()
            
            # Try to get hashes from knowledge content
            try:
                cursor.execute("SELECT question, answer FROM knowledge_content")
                for question, answer in cursor.fetchall():
                    content_hash = self._compute_hash(question + answer)
                    self.seen_hashes.add(content_hash)
            except sqlite3.Error as e:
                logger.warning(f"Error loading knowledge content hashes: {e}")
            
            logger.info(f"Loaded {len(self.seen_hashes)} content hashes for duplicate detection")
        except Exception as e:
            logger.error(f"Error loading existing hashes: {e}")
    
    def _compute_hash(self, content: str) -> str:
        """Compute a hash for content to detect duplicates.
        
        Args:
            content: String content to hash
            
        Returns:
            SHA-256 hash of the normalized content
        """
        # Normalize the content (lowercase, strip whitespace)
        normalized = ' '.join(content.lower().strip().split())
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def _contains_pii(self, text: str) -> List[Dict[str, Any]]:
        """Check if text contains personally identifiable information.
        
        Args:
            text: Text to check for PII
            
        Returns:
            List of found PII instances with type and value
        """
        found_pii = []
        
        for pii_type, pattern in self.PII_PATTERNS.items():
            matches = pattern.findall(text)
            for match in matches:
                found_pii.append({
                    'type': pii_type,
                    'value': match
                })
        
        return found_pii
    
    def _contains_toxic_language(self, text: str) -> List[str]:
        """Check if text contains toxic language.
        
        Args:
            text: Text to check for toxic content
            
        Returns:
            List of found toxic words
        """
        # Convert to lowercase for case-insensitive matching
        lower_text = text.lower()
        
        # Simple word boundary check
        words = re.findall(r'\b\w+\b', lower_text)
        found_toxic = [word for word in words if word in self.TOXIC_WORDS]
        
        return found_toxic
    
    def _is_duplicate(self, content: str) -> bool:
        """Check if content is a duplicate based on hash.
        
        Args:
            content: Content to check for duplicates
            
        Returns:
            True if content is a duplicate, False otherwise
        """
        content_hash = self._compute_hash(content)
        return content_hash in self.seen_hashes
    
    def validate_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single data entry for PII, toxic language, and duplicates.
        
        Args:
            entry: Dictionary containing entry data
            
        Returns:
            Dictionary with validation results
        """
        result = {
            'entry_id': entry.get('id', 'unknown'),
            'is_valid': True,
            'issues': []
        }
        
        # Concatenate all text fields for validation
        all_text = ' '.join([
            str(value) for key, value in entry.items() 
            if isinstance(value, (str, int, float))
        ])
        
        # Check for PII
        pii_found = self._contains_pii(all_text)
        if pii_found:
            result['is_valid'] = False
            result['issues'].append({
                'type': 'pii',
                'details': pii_found
            })
        
        # Check for toxic language
        toxic_words = self._contains_toxic_language(all_text)
        if toxic_words:
            result['is_valid'] = False
            result['issues'].append({
                'type': 'toxic',
                'details': toxic_words
            })
        
        # Check for duplicates
        if self._is_duplicate(all_text):
            result['is_valid'] = False
            result['issues'].append({
                'type': 'duplicate',
                'details': 'Content is a duplicate of existing entry'
            })
        else:
            # Add the hash to seen hashes
            content_hash = self._compute_hash(all_text)
            self.seen_hashes.add(content_hash)
        
        return result
    
    def validate_batch(self, entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Validate a batch of data entries in parallel.
        
        Args:
            entries: List of data entry dictionaries
            
        Returns:
            Tuple of (valid_entries, validation_results)
        """
        validation_results = []
        valid_entries = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_entry = {executor.submit(self.validate_entry, entry): entry for entry in entries}
            
            for future in as_completed(future_to_entry):
                entry = future_to_entry[future]
                try:
                    result = future.result()
                    validation_results.append(result)
                    if result['is_valid']:
                        valid_entries.append(entry)
                except Exception as e:
                    logger.error(f"Error validating entry: {e}")
                    validation_results.append({
                        'entry_id': entry.get('id', 'unknown'),
                        'is_valid': False,
                        'issues': [{'type': 'error', 'details': str(e)}]
                    })
        
        return valid_entries, validation_results
    
    def validate_file(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Validate entries from a file.
        
        Args:
            file_path: Path to JSON file with entries
            
        Returns:
            Tuple of (valid_entries, validation_summary)
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Handle both array and object formats
            if isinstance(data, dict) and 'entries' in data:
                entries = data['entries']
            elif isinstance(data, list):
                entries = data
            else:
                raise ValueError("File must contain either a JSON array or an object with 'entries' field")
            
            valid_entries, results = self.validate_batch(entries)
            
            # Generate summary
            total = len(entries)
            valid = len(valid_entries)
            invalid = total - valid
            
            # Count issues by type
            issue_counts = {}
            for result in results:
                if not result['is_valid']:
                    for issue in result['issues']:
                        issue_type = issue['type']
                        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
            
            summary = {
                'total_entries': total,
                'valid_entries': valid,
                'invalid_entries': invalid,
                'validation_rate': valid / total if total > 0 else 0,
                'issue_counts': issue_counts
            }
            
            return valid_entries, summary
        
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
            raise
    
    def save_valid_entries(self, entries: List[Dict[str, Any]], output_path: str) -> None:
        """Save valid entries to a file.
        
        Args:
            entries: List of valid entry dictionaries
            output_path: Path to save valid entries
        """
        try:
            with open(output_path, 'w') as f:
                json.dump(entries, f, indent=2)
            logger.info(f"Saved {len(entries)} valid entries to {output_path}")
        except Exception as e:
            logger.error(f"Error saving valid entries to {output_path}: {str(e)}")
            raise
    
    def save_validation_report(self, results: List[Dict[str, Any]], summary: Dict[str, Any], 
                               report_path: str) -> None:
        """Save validation results and summary to a report file.
        
        Args:
            results: List of validation result dictionaries
            summary: Validation summary dictionary
            report_path: Path to save validation report
        """
        try:
            report = {
                'summary': summary,
                'detailed_results': results
            }
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"Saved validation report to {report_path}")
        except Exception as e:
            logger.error(f"Error saving validation report to {report_path}: {str(e)}")
            raise

def main():
    parser = argparse.ArgumentParser(description="Validate crowdsourced data for safety and quality")
    parser.add_argument("--input", required=True, help="Input JSON file with data entries")
    parser.add_argument("--output", help="Output file for valid entries")
    parser.add_argument("--report", help="Output file for validation report")
    parser.add_argument("--db", help="Path to knowledge database for duplicate checking")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    args = parser.parse_args()
    
    # Create output paths if not specified
    if not args.output:
        base_name = os.path.splitext(args.input)[0]
        args.output = f"{base_name}_valid.json"
    
    if not args.report:
        base_name = os.path.splitext(args.input)[0]
        args.report = f"{base_name}_validation_report.json"
    
    # Initialize validator
    validator = DataValidator(db_path=args.db, max_workers=args.workers)
    
    try:
        # Process the file
        logger.info(f"Validating entries from {args.input}")
        valid_entries, summary = validator.validate_file(args.input)
        
        # Save valid entries
        validator.save_valid_entries(valid_entries, args.output)
        
        # Save validation report
        validation_results, _ = validator.validate_batch(valid_entries)
        validator.save_validation_report(validation_results, summary, args.report)
        
        # Log summary
        logger.info(f"Validation complete: {summary['valid_entries']} valid, "
                   f"{summary['invalid_entries']} invalid entries")
        for issue_type, count in summary.get('issue_counts', {}).items():
            logger.info(f"  - {issue_type}: {count} issues")
        
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
