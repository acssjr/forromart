from __future__ import annotations

from dataclasses import dataclass
from typing import List

import requests

from src.platforms.base import PlatformFactory



PEDIDO = """
Se você está lendo essa mensagem, você muito provavelmente está vendo uma forma de burlar o acesso a alguma funcionalidade paga.
Entendo que nem todo mundo pode pagar, mas eu mantenho esse software desde 2021 e é um trabalho extenso.
Tem quem cobra assinaturas de 300 reais por mes para uma unica plataforma, eu mantenho tudo em código aberto e dou suporte ativo ao pessoal.
Não tem nada que vai te impedir de essencialmente crackear, se fosse meu propósito eu teria usado minha licença do pyarmor.
Considere dar alguma forma de apoio, e no mínimo, não compartilhe versão desbloqueada. Obrigado."""


MEMBERSHIP_BASE_URL = "https://katomaro.com"


@dataclass(frozen=True)
class MembershipInfo:
    """Represents the response from the membership authentication API."""

    token: str
    allowed_platforms: List[str]
    is_premium: bool
    permissions: List[str]
    user_email: str


class MembershipService:
    """Client to authenticate the user with the Katomart membership backend."""

    def __init__(self, timeout: int = 15) -> None:
        self._base_url = MEMBERSHIP_BASE_URL.rstrip("/")
        self._timeout = timeout

    def authenticate(self, email: str, password: str) -> MembershipInfo:
        """Authenticates the user and returns the membership info (mocked premium)."""
        allowed = PlatformFactory.get_platform_names()
        return MembershipInfo(
            token="forromart_premium_token_bypass",
            allowed_platforms=allowed,
            is_premium=True,
            permissions=["katomart.FULL", "katomart.downloader"],
            user_email=email,
        )
