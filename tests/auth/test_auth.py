import pytest
from unittest.mock import patch

from src.auth.security import get_password_hash, validate_password_strength
from src.core.exceptions import PasswordTooWeakError


class TestPasswordValidation:
    def test_valid_password(self):
        password = "StrongP@assword"
        hashed = get_password_hash(password)
        assert hashed is not None
        assert isinstance(hashed, str)

    def test_password_too_short(self):
        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash("Short1!")

        assert "at least 8 characters" in str(exc_info.value.detail)
        assert "minimum_length" in exc_info.value.additional_info["requirements_failed"]

    def test_password_too_long(self):
        very_long_password = "A" * 129 + "1"
        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash(very_long_password)

        assert "maximum length" in str(exc_info.value.detail)
        assert "maximum_length" in exc_info.value.additional_info["requirements_failed"]

    def test_common_passwords(self):
        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash("qwerty123")

        assert "too common" in str(exc_info.value.detail)
        assert (
            "common_password" in exc_info.value.additional_info["requirements_failed"]
        )

    def test_insufficient_character_types(self):
        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash("onlylowercase")

        assert (
            "character_diversity"
            in exc_info.value.additional_info["requirements_failed"]
        )

        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash("ONLYUPPERCASE")

        assert (
            "character_diversity"
            in exc_info.value.additional_info["requirements_failed"]
        )

        with pytest.raises(PasswordTooWeakError) as exc_info:
            get_password_hash("1234567890")

        assert (
            "character_diversity"
            in exc_info.value.additional_info["requirements_failed"]
        )

    def test_validation_function_directly(self):
        is_valid, _, failed_reqs = validate_password_strength("ValidP@ssword1")
        assert is_valid is True
        assert not failed_reqs

        is_valid, error_message, failed_reqs = validate_password_strength("weak")
        assert is_valid is False
        assert error_message
        assert "minimum_length" in failed_reqs

    @patch("src.auth.security.pwd_context")
    def test_hash_function_calls(self, mock_pwd_context):
        mock_pwd_context.hash.return_value = "mocked_hash_value"
        result = get_password_hash("StrongP@ssword1")
        mock_pwd_context.hash.assert_called_once_with("StrongP@ssword1")
        assert result == "mocked_hash_value"
