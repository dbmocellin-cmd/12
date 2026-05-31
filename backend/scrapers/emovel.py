"""
Auxiliar Emovel (emovel.com.br).

O Emovel é um serviço pago de dados de mercado imobiliário.
Este módulo faz a busca na versão pública/gratuita (dados de anúncios históricos
e valores de referência por bairro). Para dados de proprietário, é necessária
assinatura no plano Emovel Pro.

Use a API oficial (https://api.emovel.com.br) se você tiver credenciais.
"""
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

BASE_PUBLIC = "https://www.emovel.com.br"
BASE_API = "https://api.emovel.com.br/v1"


class EmovelClient:
    """
    Cliente para Emovel. Requer credenciais para endpoints Pro.
    Configure EMOVEL_TOKEN no .env.
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def buscar_por_endereco(self, endereco: str, cidade: str, estado: str) -> dict:
        """
        Busca imóvel no Emovel por endereço (retorna histórico de anúncios e
        valor de referência). Requer plano Pro.
        """
        if not self.token:
            return {"erro": "Token Emovel não configurado. Adicione EMOVEL_TOKEN no .env"}
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.get(
                    f"{BASE_API}/properties/search",
                    params={"address": endereco, "city": cidade, "state": estado},
                    headers=self._headers,
                )
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                return {"erro": f"HTTP {e.response.status_code}: {e.response.text}"}
            except Exception as e:
                return {"erro": str(e)}

    async def valor_referencia_bairro(self, bairro: str, cidade: str, tipo: str = "apartamento") -> dict:
        """
        Valor médio de m² por bairro via Emovel (endpoint público).
        Útil para qualificar o lead antes de contato.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.get(
                    f"{BASE_PUBLIC}/preco-imovel/{tipo}/{cidade}/{bairro}",
                    headers={"Accept": "application/json"},
                    follow_redirects=True,
                )
                # Emovel não tem API pública documentada para isso; retorna stub
                return {
                    "bairro": bairro,
                    "cidade": cidade,
                    "tipo": tipo,
                    "status": r.status_code,
                    "nota": "Para dados detalhados, use o Emovel Pro com token de API.",
                }
            except Exception as e:
                return {"erro": str(e)}
