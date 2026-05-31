"""
Scraper via API interna do Viva Real.

Usa o mesmo endpoint JSON que o browser chama ao carregar resultados
(glue-api.vivareal.com.br/v2/listings). Sem Playwright, sem renderização HTML.
Mesma estrutura de resposta do Zap — ambos usam o backend "glue-api" do Grupo OLX.
"""
import logging
import re
from typing import AsyncIterator

import httpx

from backend.scrapers.base import ImovelData, polite_delay, parse_float

logger = logging.getLogger(__name__)

_BASE_API = "https://glue-api.vivareal.com.br/v2/listings"
_PAGE_SIZE = 24

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Origin": "https://www.vivareal.com.br",
    "Referer": "https://www.vivareal.com.br/",
    "X-Domain": "www.vivareal.com.br",
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
    unit_type = _UNIT_TYPES.get(tipo, "APARTMENT")
    business = "SALE" if finalidade == "venda" else "RENTAL"
    params = {
        "user": "user-type",
        "portal": "VIVAREAL",
        "business": business,
        "listingType": "USED",
        "addressState": estado.upper(),
        "addressCity": cidade.replace("-", " ").title(),
        "unitTypes": unit_type,
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

    url = "https://www.vivareal.com.br" + link.get("href", "")
    data = ImovelData(url=url, fonte="vivareal")

    data.titulo = listing.get("title")
    data.tipo = (listing.get("unitTypes") or [""])[0].lower().replace("_", " ") or None
    data.finalidade = "venda" if listing.get("businessType") == "SALE" else "aluguel"

    # Preço
    pricing = (listing.get("pricingInfos") or [{}])[0]
    preco_str = pricing.get("price") or ""
    data.preco = parse_float(preco_str) if preco_str else None

    # Área
    areas = listing.get("usableAreas") or listing.get("totalAreas") or []
    data.area = float(areas[0]) if areas else None

    # Quartos/banheiros/vagas
    bedrooms = listing.get("bedrooms") or []
    data.quartos = int(bedrooms[0]) if bedrooms else None
    bathrooms = listing.get("bathrooms") or []
    data.banheiros = int(bathrooms[0]) if bathrooms else None
    parking = listing.get("parkingSpaces") or []
    data.vagas = int(parking[0]) if parking else None

    # Endereço
    addr = listing.get("address", {})
    data.bairro = addr.get("neighborhood") or addr.get("zone")
    data.cidade = addr.get("city")
    data.estado = addr.get("state")
    parts = [addr.get("street"), addr.get("streetNumber")]
    data.endereco = " ".join(p for p in parts if p) or None

    # Anunciante / contato
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
    """Coleta anúncios do Viva Real via API JSON interna."""
    bairros = bairros or []
    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        for pagina in range(max_paginas):
            offset = pagina * _PAGE_SIZE
            params = _build_params(finalidade, tipo, estado, cidade, bairros, offset)
            logger.info("VivaReal API: página %d (offset %d)", pagina + 1, offset)
            try:
                r = await client.get(_BASE_API, params=params)
                r.raise_for_status()
                body = r.json()
            except httpx.HTTPStatusError as e:
                logger.error("VivaReal API HTTP %s na página %d: %s", e.response.status_code, pagina + 1, e)
                break
            except Exception as e:
                logger.error("VivaReal API erro na página %d: %s", pagina + 1, e)
                break

            listings = (
                body.get("search", {})
                    .get("result", {})
                    .get("listings", [])
            )
            if not listings:
                logger.info("VivaReal API: sem mais resultados na página %d", pagina + 1)
                break

            logger.info("VivaReal API: %d anúncios na página %d", len(listings), pagina + 1)
            for raw in listings:
                try:
                    imovel = _parse_listing(raw)
                    if apenas_proprietarios and not imovel.is_proprietario:
                        continue
                    yield imovel
                except Exception as e:
                    logger.error("VivaReal API: erro ao parsear anúncio: %s", e)

            if len(listings) < _PAGE_SIZE:
                break

            await polite_delay(2.0, 4.0)
