from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import ChangePasswordRequest
from app.modules.users.schemas import RoleEnum, UserCreate


class TestUserCreatePasswordSchema:
    """Pydantic-level validation of password length (issue #130)."""

    def test_71_bytes_ok(self):
        # 71 ASCII chars = 71 bytes UTF-8
        password = "a" * 71
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_72_bytes_ok(self):
        # 72 ASCII chars = 72 bytes UTF-8 (the boundary)
        password = "a" * 72
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_73_bytes_raises_validation_error(self):
        # 73 ASCII chars = 73 bytes UTF-8 (just over the limit)
        with pytest.raises(ValidationError) as exc:
            UserCreate(
                email="a@b.com",
                password="a" * 73,
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=uuid4(),
            )

        assert "password" in str(exc.value).lower() or "72" in str(exc.value)

    def test_multibyte_at_boundary_ok(self):
        # "ñ" is 2 bytes in UTF-8; 36 "ñ"s = 72 bytes (boundary)
        password = "ñ" * 36
        user = UserCreate(
            email="a@b.com",
            password=password,
            full_name="Test User",
            role=RoleEnum.admin,
            tenant_id=uuid4(),
        )

        assert user.password == password

    def test_multibyte_over_boundary_raises(self):
        # 37 "ñ"s = 74 bytes (over the limit)
        with pytest.raises(ValidationError):
            UserCreate(
                email="a@b.com",
                password="ñ" * 37,
                full_name="Test User",
                role=RoleEnum.admin,
                tenant_id=uuid4(),
            )


class TestChangePasswordRequestPasswordSchema:
    """Pydantic-level validation of changed password byte length."""

    def test_72_bytes_ok(self):
        # Includes uppercase, lowercase, and digit for strength validation.
        password = "Aa1" + ("b" * 69)
        request = ChangePasswordRequest(
            current_password="OldPassword123!",
            new_password=password,
        )

        assert request.new_password == password

    def test_multibyte_over_boundary_raises(self):
        # 3 ASCII bytes + 35 "ñ" chars * 2 bytes = 73 bytes.
        password = "Aa1" + ("ñ" * 35)

        with pytest.raises(ValidationError):
            ChangePasswordRequest(
                current_password="OldPassword123!",
                new_password=password,
            )


class TestPasswordLengthBoundaryDefenseInDepth:
    """Service-level validation of password length (issue #130 backstop)."""

    def test_72_bytes_hash_ok(self):
        from app.core.security import validate_password_length

        validate_password_length("a" * 72)

    def test_73_bytes_service_raises(self):
        from app.core.exceptions import UserError
        from app.core.security import validate_password_length

        with pytest.raises(UserError) as exc:
            validate_password_length("a" * 73)

        assert exc.value.status_code == 400
