import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ImovelData:
    url: str
    fonte: str
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    finalidade: Optional[str] = None
    preco: Optional[float] = None
    area: Optional[float] = None
    quartos: Optional[int] = None
    banheiros: Optional[int] = None
    vagas: Optional[int] = None
    endereco: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    anunciante: Optional[str] = None
    telefone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    is_proprietario: bool = False
    erros: list[str] = field(default_factory=list)


async def polite_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Rate limiting educado para não sobrecarregar os servidores."""
    await asyncio.sleep(random.uniform(min_s, max_s))


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    import re
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    import re
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def parse_float(text: str) -> Optional[float]:
    if not text:
        return None
    import re
    m = re.search(r"[\d.,]+", text)
    if not m:
        return None
    return float(m.group().replace(".", "").replace(",", "."))
