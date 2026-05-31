from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fonte: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    titulo: Mapped[str | None] = mapped_column(String(500))
    tipo: Mapped[str | None] = mapped_column(String(100))
    finalidade: Mapped[str | None] = mapped_column(String(50))

    preco: Mapped[float | None] = mapped_column(Float)
    area: Mapped[float | None] = mapped_column(Float)
    preco_m2: Mapped[float | None] = mapped_column(Float)  # calculado no insert
    quartos: Mapped[int | None] = mapped_column(Integer)
    banheiros: Mapped[int | None] = mapped_column(Integer)
    vagas: Mapped[int | None] = mapped_column(Integer)

    endereco: Mapped[str | None] = mapped_column(String(500))
    bairro: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(200))
    estado: Mapped[str | None] = mapped_column(String(2))
    # Hash para deduplicação por endereço físico (cidade+bairro+rua+número normalizado)
    endereco_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # Contato — só o mínimo necessário (princípio da minimização, LGPD Art. 6º III)
    anunciante: Mapped[str | None] = mapped_column(String(300))
    telefone: Mapped[str | None] = mapped_column(String(100))
    whatsapp: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200))
    is_proprietario: Mapped[bool] = mapped_column(Boolean, default=False)

    # Gestão de lead
    status: Mapped[str] = mapped_column(String(50), default="novo")
    # novo | contatado | negociando | captado | descartado
    anotacoes: Mapped[str | None] = mapped_column(Text)
    captado_em: Mapped[datetime | None] = mapped_column(DateTime)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_imoveis_cidade_bairro", "cidade", "bairro"),
        Index("ix_imoveis_preco_m2", "preco_m2"),
    )
