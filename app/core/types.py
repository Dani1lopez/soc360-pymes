from __future__ import annotations

from typing import Annotated

import re
from pydantic.functional_validators import AfterValidator

# RFC 5322 simplificado — valida sintaxis sin comprobar dominio ni DNS.
# Permite dominios reservados (.test, .local, .example) necesarios en tests
# y en redes internas corporativas (caso de uso SOC PYMEs).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", re.IGNORECASE)


def _validate_email_lenient(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("Formato de email inválido")
    return v


# Drop-in replacement para pydantic.EmailStr
EmailStr = Annotated[str, AfterValidator(_validate_email_lenient)]
