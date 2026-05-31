"""
Scraper via API interna do Zap Imóveis (glue-api.zapimoveis.com.br/v2/listings).

Proteções implementadas:
- Rotação de User-Agent a cada requisição
- Rate limiting: 3-7s entre páginas (24 anúncios cada)
- Backoff exponencial em erro 429 / 5xx (até 3 tentativas)
- Cap de requisições por sessão para não sobrecarregar
- Dados coletados: apenas o que é exibido publicamente no portal
"""
import logging
import re
from typing import AsyncIterator

import httpx

from backend.scrapers.base import (
    ImovelData,
    backoff_delay,
    parse_float,
    polite_delay,
    random_user_agent,
)

logger = logging.getLogger(__name__)

_BASE_API = "https://glue-api.zapimoveis.com.br/v2/listings"
_PAGE_SIZE = 24
# Máx. requisições por sessão de coleta — evita bloqueio por volume
_MAX_REQUESTS_PER_SESSION = 30

_BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": "https://www.zapimoveis.com.br",
    "Referer": "https://www.zapimoveis.com.br/",
    "X-Domain": "www.zapimoveis.com.br",
}

_UNIT_TYPES = {
    "apartamentos": "APARTMENT",
    "casas": "HOME",
    "terrenos": "LAND",
    "comercial": "COMMERCIAL_PROPERTY",
    "studio": "STUDIO",
    "kitnet": "KITNET",
    "cobertura": "PENTHOUSE",
}


def _build_params(
    finalidade: str,
    tipo: str,
    estado: str,
    cidade: str,
    bairros: list[str],
    offset: int,
) -> dict:
    params = {
        "user": "user-type",
        "portal": "ZAP",
        "business": "SALE" if finalidade == "venda" else "RENTAL",
        "listingType": "USED",
        "addressState": estado.upper(),
        "addressCity": cidade.replace("-", " ").title(),
        "unitTypes": _UNIT_TYPES.get(tipo, "APARTMENT"),
        "size": _PAGE_SIZE,
        "from": offset,
        "categoryPage": "1",
        "__vt": "hl",
    }
    if bairros:
        params["addressNeighborhood"] = ",".join(b.replace("-", " ").title() for b in bairros)
    return params


def _parse_listing(raw: dict) -> ImovelData:
    listing = raw.get("listing", raw)
    link = raw.get("link", {})
    url = "https://www.zapimoveis.com.br" + link.get("href", "")
    data = ImovelData(url=url, fonte="zapimoveis")

    data.titulo = listing.get("title")
    data.tipo = (listing.get("unitTypes") or [""])[0].lower().replace("_", " ") or None
    data.finalidade = "venda" if listing.get("businessType") == "SALE" else "aluguel"

    pricing = (listing.get("pricingInfos") or [{}])[0]
    preco_str = pricing.get("price") or ""
    data.preco = parse_float(preco_str) if preco_str else None

    areas = listing.get("usableAreas") or listing.get("totalAreas") or []
    data.area = float(areas[0]) if areas else None

    bedrooms = listing.get("bedrooms") or []
    data.quartos = int(bedrooms[0]) if bedrooms else None
    bathrooms = listing.get("bathrooms") or []
    data.banheiros = int(bathrooms[0]) if bathrooms else None
    parking = listing.get("parkingSpaces") or []
    data.vagas = int(parking[0]) if parking else None

    addr = listing.get("address", {})
    data.bairro = addr.get("neighborhood") or addr.get("zone")
    data.cidade = addr.get("city")
    data.estado = addr.get("state")
    parts = [addr.get("street"), addr.get("streetNumber")]
    data.endereco = " ".join(p for p in parts if p) or None

    advertiser = listing.get("advertiser", {})
    data.anunciante = advertiser.get("name")
    phones = advertiser.get("phones") or {}
    telefones = phones.get("phone") or phones.get("phones") or []
    if isinstance(telefones, str):
        telefones = [telefones]
    if telefones:
        data.telefone = re.sub(r"\D", "", str(telefones[0]))
    whatsapps = phones.get("whatsapp") or []
    if isinstance(whatsapps, str):
        whatsapps = [whatsapps]
    if whatsapps:
        data.whatsapp = re.sub(r"\D", "", str(whatsapps[0]))
    data.email = advertiser.get("email")

    advertiser_type = advertiser.get("type") or ""
    data.is_proprietario = advertiser_type.upper() in ("OWNER", "PARTICULAR", "PERSON")

    return data


async def scrape(
    finalidade: str,
    tipo: str,
    estado: str,
    cidade: str,
    bairros: list[str] | None = None,
    max_paginas: int = 3,
    apenas_proprietarios: bool = False,
    headless: bool = True,
) -> AsyncIterator[ImovelData]:
    """Coleta anúncios do Zap Imóveis via API JSON interna."""
    bairros = bairros or []
    requisicoes = 0

    for pagina in range(max_paginas):
        if requisicoes >= _MAX_REQUESTS_PER_SESSION:
            logger.warning("Zap: cap de %d requisições atingido, encerrando.", _MAX_REQUESTS_PER_SESSION)
            break

        offset = pagina * _PAGE_SIZE
        params = _build_params(finalidade, tipo, estado, cidade, bairros, offset)
        headers = {**_BASE_HEADERS, "User-Agent": random_user_agent()}

        tentativa = 0
        body = None
        while tentativa < 3:
            async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=True) as client:
                try:
                    logger.info("Zap: página %d (offset %d, tentativa %d)", pagina + 1, offset, tentativa + 1)
                    r = await client.get(_BASE_API, params=params)
                    requisicoes += 1

                    if r.status_code == 429:
                        retry_after = int(r.headers.get("Retry-After", 60))
                        logger.warning("Zap: 429 — aguardando %ds", retry_after)
                        await backoff_delay(tentativa)
                        tentativa += 1
                        continue

                    r.raise_for_status()
                    body = r.json()
                    break

                except httpx.HTTPStatusError as e:
                    logger.error("Zap: HTTP %s na página %d", e.response.status_code, pagina + 1)
                    if e.response.status_code >= 500:
                        tentativa += 1
                        await backoff_delay(tentativa)
                        continue
                    body = None
                    break
                except Exception as e:
                    logger.error("Zap: erro de conexão na página %d: %s", pagina + 1, e)
                    tentativa += 1
                    await backoff_delay(tentativa)

        if body is None:
            break

        listings = body.get("search", {}).get("result", {}).get("listings", [])
        if not listings:
            logger.info("Zap: sem mais resultados na página %d", pagina + 1)
            break

        logger.info("Zap: %d anúncios na página %d", len(listings), pagina + 1)
        for raw in listings:
            try:
                imovel = _parse_listing(raw)
                if apenas_proprietarios and not imovel.is_proprietario:
                    continue
                yield imovel
            except Exception as e:
                logger.error("Zap: erro ao parsear anúncio: %s", e)

        if len(listings) < _PAGE_SIZE:
            break

        await polite_delay(3.0, 7.0)
