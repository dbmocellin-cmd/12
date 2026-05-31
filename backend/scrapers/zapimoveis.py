"""
Scraper Zap Imóveis — usa Playwright para passar pelo Cloudflare e intercepta
as respostas JSON da glue-api diretamente (sem parsear HTML).
"""
import logging
import re
from typing import AsyncIterator

from backend.scrapers.base import ImovelData, parse_float
from backend.scrapers.browser import scrape_via_browser

logger = logging.getLogger(__name__)


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
    async for raw in scrape_via_browser(
        portal="ZAP",
        finalidade=finalidade,
        tipo=tipo,
        estado=estado,
        cidade=cidade,
        bairros=bairros or [],
        max_paginas=max_paginas,
        headless=headless,
    ):
        try:
            imovel = _parse_listing(raw)
            if apenas_proprietarios and not imovel.is_proprietario:
                continue
            yield imovel
        except Exception as e:
            logger.error("Zap: erro ao parsear anúncio: %s", e)
