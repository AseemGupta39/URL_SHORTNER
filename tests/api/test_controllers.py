"""
Unit tests for URL shortener controllers.

Tests the ShortenController and RedirectController by mocking the URLService layer.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock
from pydantic import HttpUrl

from app.api.controllers import ShortenController, RedirectController
from app.core.schemas import ShortenRequest, ShortenResponse, RedirectResponse
from app.core.exceptions import ShortCodeNotFoundException


class TestShortenController:
    """Test suite for ShortenController."""

    @pytest.fixture
    def mock_url_service(self):
        """Create a mock URLService."""
        return AsyncMock()

    @pytest.fixture
    def shorten_controller(self, mock_url_service):
        """Create ShortenController with mocked service."""
        return ShortenController(url_service=mock_url_service)

    @pytest.mark.asyncio
    async def test_handle_successful_shortening(self, shorten_controller, mock_url_service):
        """Test successful URL shortening."""
        # Arrange
        request = ShortenRequest(original_url="https://www.example.com/long/url")
        expected_response = ShortenResponse(
            short_code="abc1234",
            short_url="https://short.ly/abc1234",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        response = await shorten_controller.handle(request)

        # Assert
        assert response == expected_response
        mock_url_service.shorten.assert_called_once_with(request.original_url)

    @pytest.mark.asyncio
    async def test_handle_with_https_url(self, shorten_controller, mock_url_service):
        """Test shortening HTTPS URL."""
        # Arrange
        request = ShortenRequest(original_url="https://secure.example.com")
        expected_response = ShortenResponse(
            short_code="xyz7890",
            short_url="https://short.ly/xyz7890",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        response = await shorten_controller.handle(request)

        # Assert
        assert response.short_code == "xyz7890"
        assert response.short_url == "https://short.ly/xyz7890"
        mock_url_service.shorten.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_with_http_url(self, shorten_controller, mock_url_service):
        """Test shortening HTTP URL."""
        # Arrange
        request = ShortenRequest(original_url="http://example.com")
        expected_response = ShortenResponse(
            short_code="def4567",
            short_url="https://short.ly/def4567",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        response = await shorten_controller.handle(request)

        # Assert
        assert response.short_code == "def4567"
        mock_url_service.shorten.assert_called_once_with(request.original_url)

    @pytest.mark.asyncio
    async def test_handle_with_complex_url(self, shorten_controller, mock_url_service):
        """Test shortening complex URL with query parameters."""
        # Arrange
        complex_url = "https://example.com/path?param1=value1&param2=value2#fragment"
        request = ShortenRequest(original_url=complex_url)
        expected_response = ShortenResponse(
            short_code="cmplx99",
            short_url="https://short.ly/cmplx99",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        response = await shorten_controller.handle(request)

        # Assert
        assert response.short_code == "cmplx99"
        mock_url_service.shorten.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_delegates_to_service(self, shorten_controller, mock_url_service):
        """Test that controller delegates work to service layer."""
        # Arrange
        request = ShortenRequest(original_url="https://example.com")
        expected_response = ShortenResponse(
            short_code="test123",
            short_url="https://short.ly/test123",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        await shorten_controller.handle(request)

        # Assert - Verify delegation happened
        mock_url_service.shorten.assert_called_once()
        call_args = mock_url_service.shorten.call_args
        assert isinstance(call_args[0][0], HttpUrl)

    @pytest.mark.asyncio
    async def test_handle_preserves_service_response(self, shorten_controller, mock_url_service):
        """Test that controller returns service response unchanged."""
        # Arrange
        request = ShortenRequest(original_url="https://example.com")
        created_at = datetime(2024, 1, 15, 10, 30, 0)
        expected_response = ShortenResponse(
            short_code="prsrv01",
            short_url="https://short.ly/prsrv01",
            created_at=created_at
        )
        mock_url_service.shorten.return_value = expected_response

        # Act
        response = await shorten_controller.handle(request)

        # Assert - Response is unchanged
        assert response is expected_response
        assert response.created_at == created_at


class TestRedirectController:
    """Test suite for RedirectController."""

    @pytest.fixture
    def mock_url_service(self):
        """Create a mock URLService."""
        return AsyncMock()

    @pytest.fixture
    def redirect_controller(self, mock_url_service):
        """Create RedirectController with mocked service."""
        return RedirectController(url_service=mock_url_service)

    @pytest.mark.asyncio
    async def test_handle_successful_redirect(self, redirect_controller, mock_url_service):
        """Test successful URL resolution."""
        # Arrange
        short_code = "abc1234"
        expected_response = RedirectResponse(
            original_url=HttpUrl("https://www.example.com"),
            status="found"
        )
        mock_url_service.resolve.return_value = expected_response

        # Act
        response = await redirect_controller.handle(short_code)

        # Assert
        assert response == expected_response
        mock_url_service.resolve.assert_called_once_with(short_code)

    @pytest.mark.asyncio
    async def test_handle_with_valid_short_code(self, redirect_controller, mock_url_service):
        """Test resolving valid 7-character short code."""
        # Arrange
        short_code = "xyz7890"
        expected_response = RedirectResponse(
            original_url=HttpUrl("https://github.com/anthropics/claude-code"),
            status="found"
        )
        mock_url_service.resolve.return_value = expected_response

        # Act
        response = await redirect_controller.handle(short_code)

        # Assert
        assert str(response.original_url) == "https://github.com/anthropics/claude-code"
        assert response.status == "found"

    @pytest.mark.asyncio
    async def test_handle_not_found_raises_exception(self, redirect_controller, mock_url_service):
        """Test that ShortCodeNotFoundException is propagated."""
        # Arrange
        short_code = "invalid"
        mock_url_service.resolve.side_effect = ShortCodeNotFoundException(short_code)

        # Act & Assert
        with pytest.raises(ShortCodeNotFoundException) as exc_info:
            await redirect_controller.handle(short_code)

        assert exc_info.value.short_code == short_code
        mock_url_service.resolve.assert_called_once_with(short_code)

    @pytest.mark.asyncio
    async def test_handle_delegates_to_service(self, redirect_controller, mock_url_service):
        """Test that controller delegates work to service layer."""
        # Arrange
        short_code = "test123"
        expected_response = RedirectResponse(
            original_url=HttpUrl("https://example.com"),
            status="found"
        )
        mock_url_service.resolve.return_value = expected_response

        # Act
        await redirect_controller.handle(short_code)

        # Assert - Verify delegation happened
        mock_url_service.resolve.assert_called_once_with(short_code)

    @pytest.mark.asyncio
    async def test_handle_preserves_service_response(self, redirect_controller, mock_url_service):
        """Test that controller returns service response unchanged."""
        # Arrange
        short_code = "prsrv01"
        expected_response = RedirectResponse(
            original_url=HttpUrl("https://www.anthropic.com/claude"),
            status="found"
        )
        mock_url_service.resolve.return_value = expected_response

        # Act
        response = await redirect_controller.handle(short_code)

        # Assert - Response is unchanged
        assert response is expected_response
        assert str(response.original_url) == "https://www.anthropic.com/claude"

    @pytest.mark.asyncio
    async def test_handle_with_different_short_codes(self, redirect_controller, mock_url_service):
        """Test handling different short codes."""
        # Test multiple short codes
        test_cases = [
            ("abc1234", "https://example.com/1"),
            ("xyz7890", "https://example.com/2"),
            ("def4567", "https://example.com/3"),
        ]

        for short_code, url in test_cases:
            # Arrange
            expected_response = RedirectResponse(
                original_url=HttpUrl(url),
                status="found"
            )
            mock_url_service.resolve.return_value = expected_response

            # Act
            response = await redirect_controller.handle(short_code)

            # Assert
            assert str(response.original_url) == url

    @pytest.mark.asyncio
    async def test_handle_with_complex_original_url(self, redirect_controller, mock_url_service):
        """Test redirect to complex URL with parameters."""
        # Arrange
        short_code = "cmplx99"
        complex_url = "https://example.com/path?param1=value1&param2=value2#fragment"
        expected_response = RedirectResponse(
            original_url=HttpUrl(complex_url),
            status="found"
        )
        mock_url_service.resolve.return_value = expected_response

        # Act
        response = await redirect_controller.handle(short_code)

        # Assert
        assert str(response.original_url) == complex_url


class TestControllerIntegration:
    """Integration tests for controllers working together."""

    @pytest.fixture
    def mock_url_service(self):
        """Create a mock URLService for both controllers."""
        return AsyncMock()

    @pytest.fixture
    def controllers(self, mock_url_service):
        """Create both controllers with same mock service."""
        return {
            'shorten': ShortenController(url_service=mock_url_service),
            'redirect': RedirectController(url_service=mock_url_service)
        }

    @pytest.mark.asyncio
    async def test_shorten_then_redirect_flow(self, controllers, mock_url_service):
        """Test the complete flow: shorten URL then redirect."""
        # Arrange
        original_url = "https://www.example.com/very/long/url"
        short_code = "flow123"

        # Mock shorten response
        shorten_response = ShortenResponse(
            short_code=short_code,
            short_url=f"https://short.ly/{short_code}",
            created_at=datetime.now()
        )
        mock_url_service.shorten.return_value = shorten_response

        # Mock redirect response
        redirect_response = RedirectResponse(
            original_url=HttpUrl(original_url),
            status="found"
        )
        mock_url_service.resolve.return_value = redirect_response

        # Act - Shorten
        shorten_result = await controllers['shorten'].handle(
            ShortenRequest(original_url=original_url)
        )

        # Act - Redirect
        redirect_result = await controllers['redirect'].handle(short_code)

        # Assert
        assert shorten_result.short_code == short_code
        assert str(redirect_result.original_url) == original_url

    @pytest.mark.asyncio
    async def test_controllers_use_same_service_instance(self, controllers, mock_url_service):
        """Test that both controllers share the same service instance."""
        # Arrange & Act
        await controllers['shorten'].handle(
            ShortenRequest(original_url="https://example.com")
        )
        await controllers['redirect'].handle("test123")

        # Assert - Both controllers used the same mock service
        assert mock_url_service.shorten.called
        assert mock_url_service.resolve.called
