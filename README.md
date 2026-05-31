# Captação de Imóveis

Dashboard web para automatizar a captação de imóveis anunciados no Zap Imóveis e Viva Real.

## Funcionalidades

- Coleta anúncios de Zap Imóveis e/ou Viva Real em background
- Filtra por cidade, bairro, tipo, finalidade, preço e quartos
- Identifica automaticamente anúncios de proprietários (particulares)
- Exibe telefone, WhatsApp e link direto para contato
- Gestão de leads com status (novo → contatado → negociando → captado)
- Anotações por lead
- Exportação CSV
- Integração auxiliar com Emovel (requer plano Pro)

## Instalação

```bash
# 1. Crie o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# 2. Instale dependências
pip install -r backend/requirements.txt

# 3. Instale o Playwright (navegador Chromium)
playwright install chromium

# 4. Configure variáveis (opcional)
cp .env.example .env

# 5. Inicie o servidor
python run.py
```

Acesse: http://localhost:8000

## Uso

1. Vá em **Nova Coleta**
2. Escolha os portais (Zap e/ou Viva Real)
3. Preencha finalidade, tipo, estado e cidade (em slug: `sao-paulo`)
4. Opcionalmente filtre por bairros e marque "Apenas proprietários"
5. Clique em **Iniciar Coleta** — os dados aparecem na aba **Leads**
6. Gerencie status e anotações de cada lead
7. Exporte para CSV para uso no CRM

## Conformidade Legal (LGPD)

- Dados coletados são **públicos**, exibidos pelos próprios portais
- Rate limiting embutido (2–5s entre requisições) — sem sobrecarga nos servidores
- Finalidade legítima: prospecção imobiliária (Art. 10, LGPD)
- Não compartilhe nem revenda os dados coletados
- Respeite solicitações de remoção dos anunciantes

## Integração Emovel

O Emovel é um serviço pago de inteligência de mercado. Configure `EMOVEL_TOKEN` no `.env`
com seu token de API Emovel Pro para acessar dados de histórico e referência de valor por bairro.
