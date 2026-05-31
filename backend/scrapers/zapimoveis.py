"""
Scraper para Zap Imóveis (zapimoveis.com.br).

Uso: coleta anúncios de proprietários diretos (particulares) e imobiliárias.
Respeita rate limiting e não armazena dados sensíveis além do necessário.
"""
import re
import json
import logging
from typing import AsyncIterator, Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from backend.scrapers.base import ImovelData, polite_delay, parse_price, parse_int, parse_float

logger = logging.getLogger(__name__)

BASE = "https://www.zapimoveis.com.br"


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
    return f"{BASE}{path}/?pagina={pagina}"


async def _reveal_phone(page: Page, timeout: int = 5000) -> Optional[str]:
    """Clica no botão 'Ver telefone' e retorna o número revelado."""
    try:
        btn = page.locator("button:has-text('Ver telefone'), button:has-text('ver telefone')")
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_timeout(1500)
        phone_el = page.locator("[data-testid='owner-phone'], .phone, .js-phone-number, [class*='phone']")
        if await phone_el.count() > 0:
            text = await phone_el.first.inner_text()
            digits = re.sub(r"\D", "", text)
            if len(digits) >= 10:
                return digits
    except PWTimeout:
        pass
    except Exception as e:
        logger.debug("Erro ao revelar telefone: %s", e)
    return None


async def _parse_listing_page(page: Page, url: str) -> ImovelData:
    data = ImovelData(url=url, fonte="zapimoveis")

    try:
        # Título
        el = page.locator("h1")
        if await el.count() > 0:
            data.titulo = (await el.first.inner_text()).strip()

        # Preço
        preco_el = page.locator("[data-testid='price'], .price__item--main, [class*='price-info']")
        if await preco_el.count() > 0:
            data.preco = parse_price(await preco_el.first.inner_text())

        # Características via JSON-LD ou atributos
        scripts = await page.locator("script[type='application/ld+json']").all()
        for s in scripts:
            try:
                raw = await s.inner_text()
                obj = json.loads(raw)
                if obj.get("@type") in ("Apartment", "House", "RealEstateListing", "Product"):
                    data.titulo = data.titulo or obj.get("name")
                    addr = obj.get("address", {})
                    data.endereco = addr.get("streetAddress")
                    data.bairro = addr.get("addressLocality") or addr.get("neighborhood")
                    data.cidade = addr.get("addressRegion") or addr.get("addressLocality")
            except Exception:
                pass

        # Área, quartos, banheiros, vagas via ícones/atributos
        features = page.locator("[data-testid='amenities-item'], li.feature, [class*='amenitie'], [class*='feature']")
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

        # Anunciante / proprietário
        anunc_el = page.locator(
            "[data-testid='owner-name'], [data-testid='publisher-name'], "
            ".advertiser-name, [class*='publisher']"
        )
        if await anunc_el.count() > 0:
            data.anunciante = (await anunc_el.first.inner_text()).strip()

        # Detecta se é particular (proprietário)
        page_text = (await page.content()).lower()
        data.is_proprietario = any(
            kw in page_text for kw in ["particular", "proprietário", "dono do imóvel"]
        )

        # Telefone
        data.telefone = await _reveal_phone(page)

        # WhatsApp link
        wa = page.locator("a[href*='wa.me'], a[href*='whatsapp']")
        if await wa.count() > 0:
            href = await wa.first.get_attribute("href") or ""
            m = re.search(r"(\d{10,13})", href)
            if m:
                data.whatsapp = m.group(1)

        # Localização do breadcrumb / cabeçalho
        if not data.bairro:
            loc_el = page.locator("[data-testid='location'], .address, [class*='address']")
            if await loc_el.count() > 0:
                loc_text = (await loc_el.first.inner_text()).strip()
                parts = [p.strip() for p in loc_text.split(",")]
                if len(parts) >= 2:
                    data.bairro = parts[0]
                    data.cidade = parts[1]

        # Tipo de imóvel via URL
        for t in ["apartamento", "casa", "terreno", "comercial", "studio", "kitnet", "cobertura"]:
            if t in url:
                data.tipo = t
                break

        # Finalidade via URL
        data.finalidade = "venda" if "/venda/" in url else "aluguel"

    except Exception as e:
        data.erros.append(str(e))
        logger.error("Erro ao parsear %s: %s", url, e)

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
    """
    Coleta anúncios do Zap Imóveis.

    Args:
        finalidade: "venda" ou "aluguel"
        tipo: "apartamentos", "casas", "terrenos", etc.
        estado: sigla ex. "sp", "rj"
        cidade: nome da cidade ex. "sao-paulo"
        bairros: lista de bairros (opcional)
        max_paginas: limite de páginas de resultados
        apenas_proprietarios: filtra apenas anúncios de particulares
        headless: False para abrir o browser (debug)
    """
    bairros = bairros or []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        ctx.set_default_timeout(30_000)

        for pagina in range(1, max_paginas + 1):
            list_url = _build_search_url(finalidade, tipo, estado, cidade, bairros, pagina)
            page = await ctx.new_page()
            logger.info("Zap: página %d — %s", pagina, list_url)
            try:
                await page.goto(list_url, wait_until="domcontentloaded")
                await polite_delay(3, 6)

                # Coleta links dos anúncios
                links = await page.locator(
                    "a[href*='/imovel/'], a[href*='/apartamento/'], a[href*='/casa/']"
                ).all()
                hrefs = []
                for a in links:
                    href = await a.get_attribute("href")
                    if href and "/imovel/" in href:
                        full = href if href.startswith("http") else BASE + href
                        if full not in hrefs:
                            hrefs.append(full)

                logger.info("Zap: %d anúncios encontrados na página %d", len(hrefs), pagina)

                if not hrefs:
                    await page.close()
                    break

                for href in hrefs:
                    detail_page = await ctx.new_page()
                    try:
                        await detail_page.goto(href, wait_until="domcontentloaded")
                        await polite_delay(2, 4)
                        imovel = await _parse_listing_page(detail_page, href)
                        if apenas_proprietarios and not imovel.is_proprietario:
                            continue
                        yield imovel
                    except Exception as e:
                        logger.error("Zap: erro ao acessar %s: %s", href, e)
                    finally:
                        await detail_page.close()
                        await polite_delay(1.5, 3)

            except Exception as e:
                logger.error("Zap: erro na página de lista %s: %s", list_url, e)
            finally:
                await page.close()

        await browser.close()
