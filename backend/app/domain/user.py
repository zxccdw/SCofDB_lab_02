"""Доменная сущность пользователя."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .exceptions import InvalidEmailError


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


@dataclass
class User:
    """Пользователь системы."""
    
    email: str
    name: str = ""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.email or not self.email.strip():
            raise InvalidEmailError(self.email)
        
        if not EMAIL_REGEX.match(self.email):
            raise InvalidEmailError(self.email)
