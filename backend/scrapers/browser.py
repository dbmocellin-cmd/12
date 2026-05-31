"""
Utilitário compartilhado: abre o portal com Playwright, intercepta as
respostas JSON da glue-api e retorna os dados sem precisar parsear HTML.

Fluxo:
  1. Browser navega até a página de resultados (passa Cloudflare normalmente)
  2. Interceptamos a resposta da glue-api via page.route / response
  3. Extraímos o JSON diretamente — sem clicar em nada
  4. Paginamos via URL param enquanto houver resultados
"""
import asyncio
import json
import logging
from typing import Optional

from playwright.async_api import async_playwright, Page, Response

from backend.scrapers.base import polite_delay, random_user_agent

logger = logging.getLogger(__name__)

_GLUE_API_HOST = "glue-api.zapimoveis.com.br"


async def _fetch_page_json(
    page: Page,
    url: str,
    portal: str,
) -> Optional[dict]:
    """
    Navega até `url` e captura a primeira resposta da glue-api
    que contenha listings do portal esperado.
    """
    captured: list[dict] = []

    async def handle_response(response: Response):
        try:
            if _GLUE_API_HOST in response.url and "listings" in response.url:
                body = await response.json()
                if body.get("search", {}).get("result", {}).get("listings"):
                    captured.append(body)
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="networkidle", timeout=45_000)
    except Exception as e:
        logger.warning("Timeout/erro ao carregar página: %s", e)

    # Aguarda até a resposta chegar (max 10s extra)
    for _ in range(20):
        if captured:
            break
        await asyncio.sleep(0.5)

    page.remove_listener("response", handle_response)
    return captured[0] if captured else None


def build_portal_url(
    portal: str,
    finalidade: str,
    tipo: str,
    estado: str,
    cidade: str,
    bairros: list[str],
    pagina: int,
) -> str:
    base = "https://www.zapimoveis.com.br" if portal == "ZAP" else "https://www.vivareal.com.br"
    fin = "venda" if finalidade == "venda" else "aluguel"
    cidade_slug = cidade.lower()
    estado_slug = estado.lower()

    path = f"/{fin}/{tipo}/{estado_slug}+{cidade_slug}"
    if bairros:
        path += "+" + ",".join(b.lower().replace(" ", "-") for b in bairros)

    sep = "?" if portal == "ZAP" else "?__vt=hl&"
    return f"{base}{path}/{sep}pagina={pagina}"


async def scrape_via_browser(
    portal: str,           # "ZAP" ou "VIVAREAL"
    finalidade: str,
    tipo: str,
    estado: str,
    cidade: str,
    bairros: list[str],
    max_paginas: int,
    headless: bool = True,
):
    """
    Gerador assíncrono: abre o browser, intercepta respostas JSON da glue-api
    e yield cada dict de listing cru.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx = await browser.new_context(
            user_agent=random_user_agent(),
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
            # Evita detecção de headless
            java_script_enabled=True,
        )
        # Remove assinaturas de webdriver
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        ctx.set_default_timeout(45_000)

        for pagina in range(1, max_paginas + 1):
            url = build_portal_url(portal, finalidade, tipo, estado, cidade, bairros, pagina)
            logger.info("%s: abrindo página %d — %s", portal, pagina, url)

            page = await ctx.new_page()
            try:
                body = await _fetch_page_json(page, url, portal)
                if not body:
                    logger.warning("%s: sem JSON capturado na página %d", portal, pagina)
                    await page.close()
                    break

                listings = body.get("search", {}).get("result", {}).get("listings", [])
                logger.info("%s: %d anúncios na página %d", portal, len(listings), pagina)

                if not listings:
                    await page.close()
                    break

                for raw in listings:
                    yield raw

                if len(listings) < 24:
                    await page.close()
                    break

            except Exception as e:
                logger.error("%s: erro na página %d: %s", portal, pagina, e)
                await page.close()
                break
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

            await polite_delay(3.0, 6.0)

        await browser.close()
