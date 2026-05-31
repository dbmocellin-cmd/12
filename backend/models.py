from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fonte: Mapped[str] = mapped_column(String(50))          # zapimoveis | vivareal
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    titulo: Mapped[str | None] = mapped_column(String(500))
    tipo: Mapped[str | None] = mapped_column(String(100))   # apartamento, casa, etc.
    finalidade: Mapped[str | None] = mapped_column(String(50))  # venda | aluguel

    preco: Mapped[float | None] = mapped_column(Float)
    area: Mapped[float | None] = mapped_column(Float)
    quartos: Mapped[int | None] = mapped_column(Integer)
    banheiros: Mapped[int | None] = mapped_column(Integer)
    vagas: Mapped[int | None] = mapped_column(Integer)

    endereco: Mapped[str | None] = mapped_column(String(500))
    bairro: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(200))
    estado: Mapped[str | None] = mapped_column(String(2))

    # Contato (anunciante)
    anunciante: Mapped[str | None] = mapped_column(String(300))
    telefone: Mapped[str | None] = mapped_column(String(100))
    whatsapp: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200))
    is_proprietario: Mapped[bool] = mapped_column(Boolean, default=False)  # True se "Particular"

    # Gestão de lead
    status: Mapped[str] = mapped_column(String(50), default="novo")
    # novo | contatado | negociando | captado | descartado
    anotacoes: Mapped[str | None] = mapped_column(Text)
    captado_em: Mapped[datetime | None] = mapped_column(DateTime)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
