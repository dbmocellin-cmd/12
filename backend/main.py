import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database import get_db, init_db
from backend.models import Imovel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Controle de tarefas de scraping em andamento
_running_tasks: dict[str, asyncio.Task] = {}
_task_status: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    for task in _running_tasks.values():
        task.cancel()


app = FastAPI(title="Captação de Imóveis", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas ───────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    fontes: list[Literal["zapimoveis", "vivareal"]] = ["zapimoveis", "vivareal"]
    finalidade: Literal["venda", "aluguel"] = "venda"
    tipo: str = "apartamentos"
    estado: str = "sp"
    cidade: str = "sao-paulo"
    bairros: list[str] = []
    max_paginas: int = 2
    apenas_proprietarios: bool = False


class ImovelUpdate(BaseModel):
    status: Optional[str] = None
    anotacoes: Optional[str] = None
    captado_em: Optional[datetime] = None


class ImovelOut(BaseModel):
    id: int
    fonte: str
    url: str
    titulo: Optional[str]
    tipo: Optional[str]
    finalidade: Optional[str]
    preco: Optional[float]
    area: Optional[float]
    quartos: Optional[int]
    banheiros: Optional[int]
    vagas: Optional[int]
    endereco: Optional[str]
    bairro: Optional[str]
    cidade: Optional[str]
    estado: Optional[str]
    anunciante: Optional[str]
    telefone: Optional[str]
    whatsapp: Optional[str]
    email: Optional[str]
    is_proprietario: bool
    status: str
    anotacoes: Optional[str]
    captado_em: Optional[datetime]
    criado_em: datetime

    model_config = {"from_attributes": True}


# ─── Background scraping ────────────────────────────────────────────────────────

async def _run_scrape(task_id: str, req: ScrapeRequest, db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)

    _task_status[task_id] = {"status": "running", "total": 0, "novos": 0, "erros": 0}

    scrapers = []
    if "zapimoveis" in req.fontes:
        from backend.scrapers import zapimoveis
        scrapers.append(zapimoveis.scrape)
    if "vivareal" in req.fontes:
        from backend.scrapers import vivareal
        scrapers.append(vivareal.scrape)

    for scraper_fn in scrapers:
        try:
            async for imovel_data in scraper_fn(
                finalidade=req.finalidade,
                tipo=req.tipo,
                estado=req.estado,
                cidade=req.cidade,
                bairros=req.bairros,
                max_paginas=req.max_paginas,
                apenas_proprietarios=req.apenas_proprietarios,
            ):
                _task_status[task_id]["total"] += 1
                db = Session()
                try:
                    existing = db.query(Imovel).filter(Imovel.url == imovel_data.url).first()
                    if not existing:
                        imovel = Imovel(
                            fonte=imovel_data.fonte,
                            url=imovel_data.url,
                            titulo=imovel_data.titulo,
                            tipo=imovel_data.tipo,
                            finalidade=imovel_data.finalidade,
                            preco=imovel_data.preco,
                            area=imovel_data.area,
                            quartos=imovel_data.quartos,
                            banheiros=imovel_data.banheiros,
                            vagas=imovel_data.vagas,
                            endereco=imovel_data.endereco,
                            bairro=imovel_data.bairro,
                            cidade=imovel_data.cidade,
                            estado=imovel_data.estado,
                            anunciante=imovel_data.anunciante,
                            telefone=imovel_data.telefone,
                            whatsapp=imovel_data.whatsapp,
                            email=imovel_data.email,
                            is_proprietario=imovel_data.is_proprietario,
                        )
                        db.add(imovel)
                        db.commit()
                        _task_status[task_id]["novos"] += 1
                    if imovel_data.erros:
                        _task_status[task_id]["erros"] += len(imovel_data.erros)
                finally:
                    db.close()
        except asyncio.CancelledError:
            _task_status[task_id]["status"] = "cancelado"
            return
        except Exception as e:
            logger.error("Scraper falhou: %s", e)
            _task_status[task_id]["erros"] += 1

    _task_status[task_id]["status"] = "concluido"
    logger.info("Tarefa %s concluída: %s", task_id, _task_status[task_id])


# ─── Rotas de Scraping ──────────────────────────────────────────────────────────

@app.post("/api/scrape/iniciar")
async def iniciar_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    """Inicia uma tarefa de coleta em background."""
    import uuid
    task_id = str(uuid.uuid4())[:8]
    from backend.database import DATABASE_URL
    task = asyncio.create_task(_run_scrape(task_id, req, DATABASE_URL))
    _running_tasks[task_id] = task
    _task_status[task_id] = {"status": "iniciando", "total": 0, "novos": 0, "erros": 0}
    return {"task_id": task_id, "mensagem": "Coleta iniciada em background"}


@app.get("/api/scrape/status/{task_id}")
async def status_scrape(task_id: str):
    if task_id not in _task_status:
        raise HTTPException(404, "Tarefa não encontrada")
    return _task_status[task_id]


@app.delete("/api/scrape/cancelar/{task_id}")
async def cancelar_scrape(task_id: str):
    task = _running_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Tarefa não encontrada")
    task.cancel()
    return {"mensagem": "Tarefa cancelada"}


# ─── Rotas de Imóveis ──────────────────────────────────────────────────────────

@app.get("/api/imoveis", response_model=list[ImovelOut])
def listar_imoveis(
    db: Session = Depends(get_db),
    fonte: Optional[str] = None,
    finalidade: Optional[str] = None,
    cidade: Optional[str] = None,
    bairro: Optional[str] = None,
    status: Optional[str] = None,
    apenas_proprietarios: bool = False,
    preco_min: Optional[float] = None,
    preco_max: Optional[float] = None,
    quartos_min: Optional[int] = None,
    busca: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    q = db.query(Imovel)
    if fonte:
        q = q.filter(Imovel.fonte == fonte)
    if finalidade:
        q = q.filter(Imovel.finalidade == finalidade)
    if cidade:
        q = q.filter(Imovel.cidade.ilike(f"%{cidade}%"))
    if bairro:
        q = q.filter(Imovel.bairro.ilike(f"%{bairro}%"))
    if status:
        q = q.filter(Imovel.status == status)
    if apenas_proprietarios:
        q = q.filter(Imovel.is_proprietario == True)
    if preco_min is not None:
        q = q.filter(Imovel.preco >= preco_min)
    if preco_max is not None:
        q = q.filter(Imovel.preco <= preco_max)
    if quartos_min is not None:
        q = q.filter(Imovel.quartos >= quartos_min)
    if busca:
        like = f"%{busca}%"
        q = q.filter(
            or_(
                Imovel.titulo.ilike(like),
                Imovel.anunciante.ilike(like),
                Imovel.endereco.ilike(like),
                Imovel.bairro.ilike(like),
            )
        )
    total = q.count()
    items = q.order_by(Imovel.criado_em.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return items


@app.get("/api/imoveis/stats")
def stats(db: Session = Depends(get_db)):
    total = db.query(Imovel).count()
    proprietarios = db.query(Imovel).filter(Imovel.is_proprietario == True).count()
    com_telefone = db.query(Imovel).filter(Imovel.telefone != None).count()
    por_status = {}
    for row in db.query(Imovel.status, db.query(Imovel).count().label("n")).group_by(Imovel.status).all():
        pass
    from sqlalchemy import func
    for status_val, cnt in db.query(Imovel.status, func.count(Imovel.id)).group_by(Imovel.status).all():
        por_status[status_val] = cnt
    return {
        "total": total,
        "proprietarios": proprietarios,
        "com_telefone": com_telefone,
        "por_status": por_status,
    }


@app.get("/api/imoveis/{imovel_id}", response_model=ImovelOut)
def get_imovel(imovel_id: int, db: Session = Depends(get_db)):
    item = db.query(Imovel).filter(Imovel.id == imovel_id).first()
    if not item:
        raise HTTPException(404, "Imóvel não encontrado")
    return item


@app.patch("/api/imoveis/{imovel_id}", response_model=ImovelOut)
def update_imovel(imovel_id: int, body: ImovelUpdate, db: Session = Depends(get_db)):
    item = db.query(Imovel).filter(Imovel.id == imovel_id).first()
    if not item:
        raise HTTPException(404, "Imóvel não encontrado")
    if body.status is not None:
        item.status = body.status
    if body.anotacoes is not None:
        item.anotacoes = body.anotacoes
    if body.captado_em is not None:
        item.captado_em = body.captado_em
    item.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


@app.delete("/api/imoveis/{imovel_id}")
def delete_imovel(imovel_id: int, db: Session = Depends(get_db)):
    item = db.query(Imovel).filter(Imovel.id == imovel_id).first()
    if not item:
        raise HTTPException(404, "Imóvel não encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ─── Exportação CSV ─────────────────────────────────────────────────────────────

@app.get("/api/imoveis/exportar/csv")
def exportar_csv(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    apenas_proprietarios: bool = False,
):
    q = db.query(Imovel)
    if status:
        q = q.filter(Imovel.status == status)
    if apenas_proprietarios:
        q = q.filter(Imovel.is_proprietario == True)
    items = q.order_by(Imovel.criado_em.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Fonte", "Título", "Tipo", "Finalidade", "Preço", "Área",
        "Quartos", "Banheiros", "Vagas", "Endereço", "Bairro", "Cidade",
        "Anunciante", "Proprietário?", "Telefone", "WhatsApp", "Email",
        "Status", "Anotações", "URL", "Captado em",
    ])
    for i in items:
        writer.writerow([
            i.id, i.fonte, i.titulo, i.tipo, i.finalidade, i.preco, i.area,
            i.quartos, i.banheiros, i.vagas, i.endereco, i.bairro, i.cidade,
            i.anunciante, "Sim" if i.is_proprietario else "Não",
            i.telefone, i.whatsapp, i.email, i.status, i.anotacoes, i.url,
            i.captado_em,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=imoveis.csv"},
    )


# ─── Frontend ───────────────────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
