"""Tests for error handling utilities."""
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from utils.errors import (
    AppException,
    ServiceException,
    RepositoryException,
    ValidationException,
    create_error_response,
)


class TestAppExceptions:
    """Test custom exception classes."""
    
    def test_app_exception_default_values(self):
        """Test AppException default values."""
        exc = AppException("Test error")
        assert exc.message == "Test error"
        assert exc.status_code == 500
        assert exc.detail == "Test error"
        assert exc.code == "INTERNAL_ERROR"
    
    def test_app_exception_custom_values(self):
        """Test AppException with custom values."""
        exc = AppException(
            message="Custom error",
            status_code=404,
            detail="Not found",
            code="NOT_FOUND"
        )
        assert exc.message == "Custom error"
        assert exc.status_code == 404
        assert exc.detail == "Not found"
        assert exc.code == "NOT_FOUND"
    
    def test_service_exception(self):
        """Test ServiceException."""
        exc = ServiceException("Service failed", status_code=503)
        assert isinstance(exc, AppException)
        assert exc.status_code == 503
    
    def test_repository_exception(self):
        """Test RepositoryException."""
        exc = RepositoryException("DB connection failed")
        assert isinstance(exc, AppException)
        assert exc.code == "INTERNAL_ERROR"
    
    def test_validation_exception(self):
        """Test ValidationException."""
        exc = ValidationException("Invalid email", field="email")
        assert isinstance(exc, AppException)
        assert exc.status_code == 400
        assert exc.code == "VALIDATION_ERROR"
        assert exc.field == "email"


class TestCreateErrorResponse:
    """Test error response creation."""
    
    def test_basic_error_response(self):
        """Test basic error response."""
        response = create_error_response(
            status_code=400,
            code="BAD_REQUEST",
            message="Invalid input"
        )
        assert response["error"]["code"] == "BAD_REQUEST"
        assert response["error"]["message"] == "Invalid input"
        assert "details" not in response["error"]
    
    def test_error_response_with_details(self):
        """Test error response with details."""
        response = create_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Validation failed",
            details={"field": "email", "reason": "invalid format"}
        )
        assert response["error"]["details"]["field"] == "email"
        assert response["error"]["details"]["reason"] == "invalid format"
