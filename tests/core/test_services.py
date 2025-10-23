"""
Comprehensive test suite for URLService business logic.
"""
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from pydantic import HttpUrl

from app.core.services import URLService
from app.core.schemas import URLData, ShortenResponse, RedirectResponse
from app.core.exceptions import ShortCodeNotFoundException
from app.data.repositories import URLRepository
from app.utils.id_generator import IDGenerator


@pytest_asyncio.fixture
async def mock_repository():
    """Mock URLRepository for testing."""
    repo = AsyncMock(spec=URLRepository)
    return repo


@pytest_asyncio.fixture
async def mock_id_generator():
    """Mock IDGenerator for testing."""
    generator = AsyncMock(spec=IDGenerator)
    return generator


@pytest_asyncio.fixture
async def url_service(mock_repository, mock_id_generator):
    """Create URLService instance with mocked dependencies."""
    return URLService(
        url_repo=mock_repository,
        id_generator=mock_id_generator,
        base_domain="short.ly"
    )


class TestURLServiceShorten:
    """Test URLService.shorten() method."""

    @pytest.mark.asyncio
    async def test_shorten_success(self, url_service, mock_id_generator, mock_repository):
        """Test successful URL shortening."""
        # Setup mocks
        mock_id_generator.generate_short_code.return_value = "abc1234"
        created_url_data = URLData(
            short_code="abc1234",
            original_url="https://example.com",
            created_at=datetime.now()
        )
        mock_repository.create.return_value = created_url_data

        # Execute
        result = await url_service.shorten(HttpUrl("https://example.com"))

        # Verify
        assert isinstance(result, ShortenResponse)
        assert result.short_code == "abc1234"
        assert result.short_url == "https://short.ly/abc1234"
        assert isinstance(result.created_at, datetime)

        # Verify mocks were called
        mock_id_generator.generate_short_code.assert_called_once()
        mock_repository.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_shorten_creates_url_data_with_correct_fields(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test that shorten creates URLData with all required fields."""
        mock_id_generator.generate_short_code.return_value = "xyz789"
        mock_repository.create.return_value = URLData(
            short_code="xyz789",
            original_url="https://test.com/path",
            created_at=datetime.now()
        )

        await url_service.shorten(HttpUrl("https://test.com/path"))

        # Verify URLData passed to repository
        call_args = mock_repository.create.call_args[0][0]
        assert isinstance(call_args, URLData)
        assert call_args.short_code == "xyz789"
        assert call_args.original_url == "https://test.com/path"
        assert isinstance(call_args.created_at, datetime)

    @pytest.mark.asyncio
    async def test_shorten_with_long_url(self, url_service, mock_id_generator, mock_repository):
        """Test shortening a very long URL."""
        long_url = "https://example.com/" + "a" * 2000
        mock_id_generator.generate_short_code.return_value = "long123"
        mock_repository.create.return_value = URLData(
            short_code="long123",
            original_url=long_url,
            created_at=datetime.now()
        )

        result = await url_service.shorten(HttpUrl(long_url))

        assert result.short_code == "long123"
        assert result.short_url == "https://short.ly/long123"

    @pytest.mark.asyncio
    async def test_shorten_with_query_parameters(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test shortening URL with query parameters."""
        url_with_query = "https://example.com/path?foo=bar&baz=qux"
        mock_id_generator.generate_short_code.return_value = "query1"
        mock_repository.create.return_value = URLData(
            short_code="query1",
            original_url=url_with_query,
            created_at=datetime.now()
        )

        result = await url_service.shorten(HttpUrl(url_with_query))

        assert result.short_code == "query1"
        # Verify original URL is preserved
        call_args = mock_repository.create.call_args[0][0]
        assert call_args.original_url == url_with_query

    @pytest.mark.asyncio
    async def test_shorten_multiple_urls_generates_unique_codes(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test that multiple URL shortenings generate unique codes."""
        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3"
        ]
        codes = ["code1", "code2", "code3"]

        for i, (url, code) in enumerate(zip(urls, codes)):
            mock_id_generator.generate_short_code.return_value = code
            mock_repository.create.return_value = URLData(
                short_code=code,
                original_url=url,
                created_at=datetime.now()
            )

            result = await url_service.shorten(HttpUrl(url))
            assert result.short_code == code


class TestURLServiceResolve:
    """Test URLService.resolve() method."""

    @pytest.mark.asyncio
    async def test_resolve_success(self, url_service, mock_repository):
        """Test successful short code resolution."""
        # Setup mock
        mock_repository.get_by_short_code.return_value = URLData(
            short_code="abc1234",
            original_url="https://example.com",
            created_at=datetime.now()
        )

        # Execute
        result = await url_service.resolve("abc1234")

        # Verify
        assert isinstance(result, RedirectResponse)
        assert result.original_url == HttpUrl("https://example.com")
        assert result.status == "found"

        # Verify mock was called
        mock_repository.get_by_short_code.assert_called_once_with("abc1234")

    @pytest.mark.asyncio
    async def test_resolve_not_found_raises_exception(self, url_service, mock_repository):
        """Test that resolving non-existent code raises ShortCodeNotFoundException."""
        # Setup mock to return None
        mock_repository.get_by_short_code.return_value = None

        # Execute and verify exception
        with pytest.raises(ShortCodeNotFoundException) as exc_info:
            await url_service.resolve("notfound")

        assert exc_info.value.short_code == "notfound"
        assert "notfound" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resolve_preserves_query_parameters(self, url_service, mock_repository):
        """Test that resolve preserves query parameters in original URL."""
        url_with_query = "https://example.com/path?foo=bar&baz=qux#section"
        mock_repository.get_by_short_code.return_value = URLData(
            short_code="query1",
            original_url=url_with_query,
            created_at=datetime.now()
        )

        result = await url_service.resolve("query1")

        assert str(result.original_url) == url_with_query

    @pytest.mark.asyncio
    async def test_resolve_multiple_codes(self, url_service, mock_repository):
        """Test resolving multiple different short codes."""
        test_cases = [
            ("code1", "https://example.com/1"),
            ("code2", "https://example.com/2"),
            ("code3", "https://example.com/3"),
        ]

        for short_code, original_url in test_cases:
            mock_repository.get_by_short_code.return_value = URLData(
                short_code=short_code,
                original_url=original_url,
                created_at=datetime.now()
            )

            result = await url_service.resolve(short_code)
            assert str(result.original_url) == original_url


class TestURLServiceIntegration:
    """Integration tests for URLService workflows."""

    @pytest.mark.asyncio
    async def test_shorten_and_resolve_workflow(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test complete workflow of shortening and then resolving a URL."""
        original_url = "https://example.com/workflow"
        short_code = "work123"

        # Setup mocks for shorten
        mock_id_generator.generate_short_code.return_value = short_code
        mock_repository.create.return_value = URLData(
            short_code=short_code,
            original_url=original_url,
            created_at=datetime.now()
        )

        # Shorten
        shorten_result = await url_service.shorten(HttpUrl(original_url))
        assert shorten_result.short_code == short_code

        # Setup mock for resolve
        mock_repository.get_by_short_code.return_value = URLData(
            short_code=short_code,
            original_url=original_url,
            created_at=datetime.now()
        )

        # Resolve
        resolve_result = await url_service.resolve(short_code)
        assert str(resolve_result.original_url) == original_url

    @pytest.mark.asyncio
    async def test_service_uses_base_domain_correctly(
        self, mock_repository, mock_id_generator
    ):
        """Test that URLService uses the provided base_domain."""
        custom_domain = "myshort.link"
        service = URLService(
            url_repo=mock_repository,
            id_generator=mock_id_generator,
            base_domain=custom_domain
        )

        mock_id_generator.generate_short_code.return_value = "test123"
        mock_repository.create.return_value = URLData(
            short_code="test123",
            original_url="https://example.com",
            created_at=datetime.now()
        )

        result = await service.shorten(HttpUrl("https://example.com"))

        assert result.short_url == f"https://{custom_domain}/test123"


class TestURLServiceEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_shorten_url_with_special_characters(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test shortening URL with special characters."""
        special_url = "https://example.com/path?query=value&foo=bar#section"
        mock_id_generator.generate_short_code.return_value = "spec123"
        mock_repository.create.return_value = URLData(
            short_code="spec123",
            original_url=special_url,
            created_at=datetime.now()
        )

        result = await url_service.shorten(HttpUrl(special_url))

        assert result.short_code == "spec123"

    @pytest.mark.asyncio
    async def test_resolve_empty_short_code_not_found(self, url_service, mock_repository):
        """Test that resolving empty/invalid code raises exception."""
        mock_repository.get_by_short_code.return_value = None

        with pytest.raises(ShortCodeNotFoundException):
            await url_service.resolve("")

    @pytest.mark.asyncio
    async def test_shorten_timestamp_is_current(
        self, url_service, mock_id_generator, mock_repository
    ):
        """Test that shorten creates URLData with current timestamp."""
        mock_id_generator.generate_short_code.return_value = "time123"

        # Capture the URLData passed to repository
        captured_url_data = None

        async def capture_create(url_data):
            nonlocal captured_url_data
            captured_url_data = url_data
            return url_data

        mock_repository.create.side_effect = capture_create

        await url_service.shorten(HttpUrl("https://example.com"))

        # Verify timestamp is recent (within last second)
        assert captured_url_data is not None
        time_diff = (datetime.now() - captured_url_data.created_at).total_seconds()
        assert time_diff < 1.0
