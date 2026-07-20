"""
Input validation for API requests.
"""
import re
from typing import Optional
from fastapi import HTTPException


def validate_message(message: str, max_length: int = 2000) -> str:
    """Validate a chat message. Raises HTTPException on failure."""
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    message = message.strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be only whitespace")
    
    if len(message) > max_length:
        raise HTTPException(status_code=413, detail=f"Message too long. Maximum length is {max_length} characters")
    
    if _contains_malicious_patterns(message):
        raise HTTPException(status_code=400, detail="Message contains invalid characters or patterns")
    
    return message


def _contains_malicious_patterns(text: str) -> bool:
    """Check for null bytes and excessive repeated characters."""
    if '\x00' in text:
        return True
    if re.search(r'(.)\1{50,}', text):
        return True
    return False


def validate_conversation_id(conversation_id: Optional[str]) -> Optional[str]:
    """Validate a conversation ID. Returns None if empty, raises HTTPException on bad format."""
    if conversation_id is None:
        return None
    
    conversation_id = conversation_id.strip()
    if not conversation_id:
        return None
    
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    
    if not uuid_pattern.match(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation ID format. Expected UUID.")
    
    return conversation_id


def sanitize_input(text: str) -> str:
    """Strip control characters and normalize whitespace."""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = ' '.join(text.split())
    return text
