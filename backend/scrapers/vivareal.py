"""
Scraper para Viva Real (vivareal.com.br).

Mesmo grupo que Zap Imóveis (OLX Group), estrutura HTML similar.
Respeita rate limiting — mínimo 2s entre requisições.
"""
import re
import json
import logging
from typing import AsyncIterator, Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from backend.scrapers.base import ImovelData, polite_delay, parse_price, parse_int, parse_float

logger = logging.getLogger(__name__)

BASE = "https://www.vivareal.com.br"


def _build_search_url(
    finalidade: str,
    tipo: str,
    estado: str,
    cidade: str,
    bairros: list[str],
    pagina: int = 1,
) -> str:
    finalidade_slug = "venda" if finalidade == "venda" else "aluguel"
    cidade_slug = cidade.lower().replace(" ", "-")
    estado_slug = estado.lower()
    bairros_slug = ",".join(b.lower().replace(" ", "-") for b in bairros) if bairros else ""
    path = f"/{finalidade_slug}/{tipo}/{estado_slug}+{cidade_slug}"
    if bairros_slug:
        path += f"+{bairros_slug}"
    return f"{BASE}{path}/?__vt=hl&page={pagina}"


async def _reveal_phone(page: Page) -> Optional[str]:
    try:
        btn = page.locator("button:has-text('Ver telefone'), [data-testid='phone-button']")
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_timeout(1500)
        phone_el = page.locator("[data-testid='phone'], [class*='phone-number'], .phone-link")
        if await phone_el.count() > 0:
            text = await phone_el.first.inner_text()
            digits = re.sub(r"\D", "", text)
            if len(digits) >= 10:
                return digits
    except PWTimeout:
        pass
    except Exception as e:
        logger.debug("Erro ao revelar telefone VR: %s", e)
    return None


async def _parse_listing_page(page: Page, url: str) -> ImovelData:
    data = ImovelData(url=url, fonte="vivareal")

    try:
        # Título
        h1 = page.locator("h1")
        if await h1.count() > 0:
            data.titulo = (await h1.first.inner_text()).strip()

        # Preço
        preco_el = page.locator("[data-testid='price-info-value'], [class*='price__value'], .price-info__value")
        if await preco_el.count() > 0:
            data.preco = parse_price(await preco_el.first.inner_text())

        # JSON-LD
        scripts = await page.locator("script[type='application/ld+json']").all()
        for s in scripts:
            try:
                raw = await s.inner_text()
                obj = json.loads(raw)
                addr = obj.get("address", {})
                data.bairro = data.bairro or addr.get("neighborhood") or addr.get("addressLocality")
                data.cidade = data.cidade or addr.get("addressRegion")
                data.endereco = data.endereco or addr.get("streetAddress")
            except Exception:
                pass

        # Features
        features = page.locator(
            "[data-testid='amenity-label'], [class*='amenitie__text'], "
            "li[class*='feature'], [class*='amenities'] li"
        )
        count = await features.count()
        for i in range(count):
            text = (await features.nth(i).inner_text()).lower()
            if "m²" in text or "m2" in text:
                data.area = data.area or parse_float(text)
            elif "quarto" in text or "dorm" in text:
                data.quartos = data.quartos or parse_int(text)
            elif "banheiro" in text:
                data.banheiros = data.banheiros or parse_int(text)
            elif "vaga" in text or "garagem" in text:
                data.vagas = data.vagas or parse_int(text)

        # Anunciante
        anunc = page.locator("[data-testid='publisher-name'], [class*='owner-name'], .advertiser__name")
        if await anunc.count() > 0:
            data.anunciante = (await anunc.first.inner_text()).strip()

        # Proprietário?
        page_text = (await page.content()).lower()
        data.is_proprietario = any(
            kw in page_text for kw in ["particular", "proprietário", "dono do imóvel"]
        )

        # Telefone
        data.telefone = await _reveal_phone(page)

        # WhatsApp
        wa = page.locator("a[href*='wa.me'], a[href*='whatsapp.com']")
        if await wa.count() > 0:
            href = await wa.first.get_attribute("href") or ""
            m = re.search(r"(\d{10,13})", href)
            if m:
                data.whatsapp = m.group(1)

        # Localização fallback
        if not data.bairro:
            loc = page.locator("[data-testid='location-info'], .location-info__address, [class*='address']")
            if await loc.count() > 0:
                parts = [(await loc.first.inner_text()).strip().split(",")]
                if parts and len(parts[0]) >= 2:
                    data.bairro = parts[0][0].strip()
                    data.cidade = parts[0][1].strip()

        # Tipo e finalidade via URL
        for t in ["apartamento", "casa", "terreno", "comercial", "studio", "kitnet", "cobertura"]:
            if t in url:
                data.tipo = t
                break
        data.finalidade = "venda" if "/venda/" in url else "aluguel"

    except Exception as e:
        data.erros.append(str(e))
        logger.error("Erro ao parsear VR %s: %s", url, e)

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
    """Coleta anúncios do Viva Real."""
    bairros = bairros or []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1366, "height": 768},
        )
        ctx.set_default_timeout(30_000)

        for pagina in range(1, max_paginas + 1):
            list_url = _build_search_url(finalidade, tipo, estado, cidade, bairros, pagina)
            page = await ctx.new_page()
            logger.info("VivaReal: página %d — %s", pagina, list_url)
            try:
                await page.goto(list_url, wait_until="domcontentloaded")
                await polite_delay(3, 6)

                links = await page.locator("a[href*='/imovel/']").all()
                hrefs = []
                for a in links:
                    href = await a.get_attribute("href")
                    if href and "/imovel/" in href:
                        full = href if href.startswith("http") else BASE + href
                        if full not in hrefs:
                            hrefs.append(full)

                logger.info("VivaReal: %d anúncios na página %d", len(hrefs), pagina)

                if not hrefs:
                    await page.close()
                    break

                for href in hrefs:
                    detail = await ctx.new_page()
                    try:
                        await detail.goto(href, wait_until="domcontentloaded")
                        await polite_delay(2, 4)
                        imovel = await _parse_listing_page(detail, href)
                        if apenas_proprietarios and not imovel.is_proprietario:
                            continue
                        yield imovel
                    except Exception as e:
                        logger.error("VR: erro em %s: %s", href, e)
                    finally:
                        await detail.close()
                        await polite_delay(1.5, 3)

            except Exception as e:
                logger.error("VR: erro na listagem %s: %s", list_url, e)
            finally:
                await page.close()

        await browser.close()
