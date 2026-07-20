"""
Input validation utilities for API requests.
"""
import re
from typing import Optional
from fastapi import HTTPException


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_message(message: str, max_length: int = 2000) -> str:
    """
    Validate a chat message.
    
    Args:
        message: The message to validate
        max_length: Maximum allowed length
        
    Returns:
        The validated message (stripped)
        
    Raises:
        HTTPException: If validation fails
    """
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    message = message.strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be only whitespace")
    
    if len(message) > max_length:
        raise HTTPException(
            status_code=413, 
            detail=f"Message too long. Maximum length is {max_length} characters"
        )
    
    # Check for potentially malicious patterns
    if _contains_malicious_patterns(message):
        raise HTTPException(
            status_code=400, 
            detail="Message contains invalid characters or patterns"
        )
    
    return message


def _contains_malicious_patterns(text: str) -> bool:
    """
    Check for potentially malicious patterns in text.
    
    This is a basic check - should be complemented by proper
    sanitization at the database/query level.
    """
    # Check for null bytes
    if '\x00' in text:
        return True
    
    # Check for excessive repeated characters (potential DoS)
    if re.search(r'(.)\1{50,}', text):
        return True
    
    return False


def validate_conversation_id(conversation_id: Optional[str]) -> Optional[str]:
    """
    Validate a conversation ID if provided.
    
    Args:
        conversation_id: The conversation ID to validate
        
    Returns:
        The validated conversation ID or None
        
    Raises:
        HTTPException: If validation fails
    """
    if conversation_id is None:
        return None
    
    conversation_id = conversation_id.strip()
    
    if not conversation_id:
        return None
    
    # UUID format check (basic)
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    
    if not uuid_pattern.match(conversation_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID format. Expected UUID."
        )
    
    return conversation_id


def sanitize_input(text: str) -> str:
    """
    Basic input sanitization.
    
    Note: This is NOT a substitute for proper parameterized queries
    and output encoding. Use this as an additional layer of defense.
    
    Args:
        text: Text to sanitize
        
    Returns:
        Sanitized text
    """
    # Remove control characters except newlines and tabs
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    # Normalize whitespace
    text = ' '.join(text.split())
    
    return text
