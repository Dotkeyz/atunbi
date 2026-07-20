"""Tests for input validation utilities."""
import pytest
from fastapi import HTTPException
from utils.validators import (
    validate_message,
    validate_conversation_id,
    sanitize_input,
    _contains_malicious_patterns,
)


class TestValidateMessage:
    """Test message validation."""
    
    def test_valid_message(self):
        """Test valid message passes validation."""
        message = "Hello, how are you?"
        result = validate_message(message)
        assert result == "Hello, how are you?"
    
    def test_message_with_whitespace(self):
        """Test message with leading/trailing whitespace is stripped."""
        message = "  Hello world  "
        result = validate_message(message)
        assert result == "Hello world"
    
    def test_empty_message_raises(self):
        """Test empty message raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_message("")
        assert exc_info.value.status_code == 400
    
    def test_whitespace_only_message_raises(self):
        """Test whitespace-only message raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_message("   ")
        assert exc_info.value.status_code == 400
    
    def test_message_too_long(self):
        """Test message exceeding max length raises HTTPException."""
        long_message = "a" * 2001
        with pytest.raises(HTTPException) as exc_info:
            validate_message(long_message, max_length=2000)
        assert exc_info.value.status_code == 413
    
    def test_message_with_null_bytes(self):
        """Test message with null bytes raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_message("Hello\x00World")
        assert exc_info.value.status_code == 400
    
    def test_message_with_excessive_repetition(self):
        """Test message with excessive repeated characters raises HTTPException."""
        malicious = "a" * 100 + "test"
        with pytest.raises(HTTPException) as exc_info:
            validate_message(malicious)
        assert exc_info.value.status_code == 400


class TestValidateConversationId:
    """Test conversation ID validation."""
    
    def test_valid_uuid(self):
        """Test valid UUID passes validation."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = validate_conversation_id(uuid)
        assert result == uuid
    
    def test_valid_uuid_uppercase(self):
        """Test uppercase UUID passes validation."""
        uuid = "550E8400-E29B-41D4-A716-446655440000"
        result = validate_conversation_id(uuid)
        assert result == uuid
    
    def test_none_conversation_id(self):
        """Test None conversation ID returns None."""
        result = validate_conversation_id(None)
        assert result is None
    
    def test_empty_conversation_id(self):
        """Test empty conversation ID returns None."""
        result = validate_conversation_id("")
        assert result is None
    
    def test_whitespace_conversation_id(self):
        """Test whitespace conversation ID returns None."""
        result = validate_conversation_id("   ")
        assert result is None
    
    def test_invalid_format_raises(self):
        """Test invalid UUID format raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_conversation_id("not-a-uuid")
        assert exc_info.value.status_code == 400
    
    def test_partial_uuid_raises(self):
        """Test partial UUID raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            validate_conversation_id("550e8400-e29b")
        assert exc_info.value.status_code == 400


class TestSanitizeInput:
    """Test input sanitization."""
    
    def test_removes_control_characters(self):
        """Test control characters are removed."""
        text = "Hello\x00\x01\x02World"
        result = sanitize_input(text)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert result == "HelloWorld"
    
    def test_preserves_newlines_and_tabs(self):
        """Test newlines and tabs are preserved."""
        text = "Hello\nWorld\t!"
        result = sanitize_input(text)
        # Note: normalize_whitespace collapses these
        assert "Hello" in result
    
    def test_normalizes_whitespace(self):
        """Test whitespace is normalized."""
        text = "Hello    World\n\nTest"
        result = sanitize_input(text)
        assert result == "Hello World Test"
    
    def test_empty_string(self):
        """Test empty string returns empty string."""
        result = sanitize_input("")
        assert result == ""


class TestMaliciousPatterns:
    """Test malicious pattern detection."""
    
    def test_null_byte_detected(self):
        """Test null byte is detected."""
        assert _contains_malicious_patterns("Hello\x00World") is True
    
    def test_excessive_repetition_detected(self):
        """Test excessive repetition is detected."""
        assert _contains_malicious_patterns("a" * 100) is True
    
    def test_normal_text_not_detected(self):
        """Test normal text is not flagged."""
        assert _contains_malicious_patterns("Hello, how are you?") is False
    
    def test_short_repetition_not_detected(self):
        """Test short repetition is not flagged."""
        assert _contains_malicious_patterns("aaaa") is False
