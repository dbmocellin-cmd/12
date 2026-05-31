import asyncio
import hashlib
import random
import re
import unicodedata
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


# User-Agents reais de browsers comuns — rotacionados a cada requisição
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def random_user_agent() -> str:
    return random.choice(_USER_AGENTS)


async def polite_delay(min_s: float = 3.0, max_s: float = 7.0):
    """
    Atraso aleatório entre requisições.
    Intervalo padrão: 3-7s — bem abaixo do limiar de detecção de bots
    dos portais (que geralmente bloqueiam rajadas < 1s).
    """
    await asyncio.sleep(random.uniform(min_s, max_s))


async def backoff_delay(tentativa: int):
    """Espera exponencial após erro: 10s, 20s, 40s."""
    wait = min(10 * (2 ** tentativa), 120)
    jitter = random.uniform(0, wait * 0.2)
    await asyncio.sleep(wait + jitter)


def normalizar_texto(s: str) -> str:
    """Remove acentos, lowercase, colapsa espaços."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def calcular_endereco_hash(
    cidade: Optional[str],
    bairro: Optional[str],
    endereco: Optional[str],
) -> Optional[str]:
    """
    SHA-1 truncado de 'cidade|bairro|rua numero' normalizado.
    Usado para detectar duplicatas entre portais (mesmo imóvel anunciado
    no Zap e no Viva Real ao mesmo tempo).
    Retorna None se não houver dados suficientes para identificar o endereço.
    """
    partes = [cidade, bairro, endereco]
    if not any(partes):
        return None
    chave = "|".join(normalizar_texto(p) if p else "" for p in partes)
    if not chave.replace("|", "").strip():
        return None
    return hashlib.sha1(chave.encode()).hexdigest()[:16]


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def parse_float(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d.,]+", text)
    if not m:
        return None
    return float(m.group().replace(".", "").replace(",", "."))
