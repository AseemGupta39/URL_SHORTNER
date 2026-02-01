"""
BaseEncoder - A flexible base encoding/decoding utility.

Supports encoding and decoding integers to/from any base using a custom alphabet.
Common use cases: Base62 for short URLs, Base36 for case-insensitive codes, etc.
"""

import logging

logger = logging.getLogger(__name__)


class BaseEncoder:
    """
    Encode and decode integers using a configurable base alphabet.

    Examples:
        # Base62 for short URLs
        encoder = BaseEncoder(62)
        code = encoder.encode(123456789)  # "8M0kX"
        num = encoder.decode("8M0kX")     # 123456789

        # Base36 (case-insensitive)
        encoder = BaseEncoder(36)
        code = encoder.encode(123456789)  # "21I3V9"

        # Custom alphabet
        encoder = BaseEncoder(alphabet="ABCDEFGH")  # Base8 with custom chars
    """

    # Default alphabets for common bases
    DEFAULT_ALPHABETS = {
        2: "01",
        8: "01234567",
        10: "0123456789",
        16: "0123456789ABCDEF",
        36: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        62: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        64: "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/",
    }

    def __init__(self, base: int = 62, alphabet: str | None = None, padding: int = 0):
        """
        Initialize BaseEncoder with specified base and optional custom alphabet.

        Args:
            base: The numeric base for encoding (2-64). Ignored if alphabet provided.
            alphabet: Custom alphabet string. Length determines the base.
            padding: Minimum output length (left-pad with first alphabet char).

        Raises:
            ValueError: If base is invalid or alphabet has duplicate characters.
        """
        if alphabet is not None:
            # Custom alphabet provided
            self._alphabet = alphabet
            self._base = len(alphabet)
        else:
            # Use default alphabet for the base
            if base not in self.DEFAULT_ALPHABETS:
                raise ValueError(
                    f"No default alphabet for base {base}. "
                    f"Supported bases: {sorted(self.DEFAULT_ALPHABETS.keys())}. "
                    f"Or provide a custom alphabet."
                )
            self._alphabet = self.DEFAULT_ALPHABETS[base]
            self._base = base

        # Validate alphabet has no duplicates
        if len(self._alphabet) != len(set(self._alphabet)):
            raise ValueError("Alphabet must not contain duplicate characters")

        if len(self._alphabet) < 2:
            raise ValueError("Alphabet must have at least 2 characters")

        self._padding = padding

        # Build reverse lookup for O(1) decoding
        self._char_to_value = {char: idx for idx, char in enumerate(self._alphabet)}

        logger.debug(
            f"BaseEncoder initialized: base={self._base}, padding={self._padding}, "
            f"alphabet_preview={self._alphabet[:10]}..."
        )

    @property
    def base(self) -> int:
        """Get the numeric base."""
        return self._base

    @property
    def alphabet(self) -> str:
        """Get the alphabet string."""
        return self._alphabet

    @property
    def padding(self) -> int:
        """Get the padding length."""
        return self._padding

    def encode(self, num: int, padding: int | None = None) -> str:
        """
        Encode an integer to a string using the configured base.

        Args:
            num: Non-negative integer to encode.
            padding: Override default padding for this call.

        Returns:
            Encoded string representation.

        Raises:
            ValueError: If num is negative.
        """
        if num < 0:
            raise ValueError(f"Cannot encode negative number: {num}")

        if num == 0:
            result = self._alphabet[0]
        else:
            chars = []
            while num > 0:
                chars.append(self._alphabet[num % self._base])
                num //= self._base
            result = ''.join(reversed(chars))

        # Apply padding
        pad_length = padding if padding is not None else self._padding
        if pad_length > 0:
            result = result.rjust(pad_length, self._alphabet[0])

        return result

    def decode(self, encoded: str) -> int:
        """
        Decode a string back to an integer.

        Args:
            encoded: String to decode.

        Returns:
            Decoded integer value.

        Raises:
            ValueError: If string contains invalid characters.
        """
        if not encoded:
            raise ValueError("Cannot decode empty string")

        num = 0
        for char in encoded:
            if char not in self._char_to_value:
                raise ValueError(
                    f"Invalid character '{char}' for base-{self._base} decoding"
                )
            num = num * self._base + self._char_to_value[char]

        return num

    def is_valid(self, encoded: str) -> bool:
        """
        Check if a string is valid for this encoder's alphabet.

        Args:
            encoded: String to validate.

        Returns:
            True if all characters are in the alphabet.
        """
        return all(char in self._char_to_value for char in encoded)

    def __repr__(self) -> str:
        return f"BaseEncoder(base={self._base}, padding={self._padding})"


# Pre-configured encoders for common use cases
Base62Encoder = lambda padding=0: BaseEncoder(base=62, padding=padding)
Base36Encoder = lambda padding=0: BaseEncoder(base=36, padding=padding)
Base16Encoder = lambda padding=0: BaseEncoder(base=16, padding=padding)
