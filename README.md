# Crypto Signals Bot

Bot de análise técnica para criptomoedas com interface web.

## Funcionalidades

- Análise de sinais em múltiplos timeframes (1h, 2h, 1d)
- Interface web em tempo real
- Monitoramento de múltiplos pares de criptomoedas
- Notificações por email para novos sinais
- Indicadores técnicos: Heikin Ashi e Chandelier Exit

## Instalação Local

1. Clone o repositório:
```bash
git clone <seu-repositorio>
cd <pasta-do-projeto>
```

2. Crie e ative um ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente:
- Crie um arquivo `.env` na raiz do projeto
- Adicione suas configurações:
```
EMAIL_FROM=seu-email@gmail.com
EMAIL_PASS=sua-senha-de-app
EMAIL_TO=destinatario@email.com
```

5. Execute o servidor:
```bash
python crypto_web.py
```

## Deploy no Render

1. Faça fork deste repositório para sua conta do GitHub

2. No Render:
   - Crie uma nova "Web Service"
   - Conecte com seu repositório do GitHub
   - Selecione a branch principal
   - Configure as variáveis de ambiente:
     - EMAIL_FROM
     - EMAIL_PASS
     - EMAIL_TO

3. O deploy será automático após cada push para a branch principal

## Tecnologias Utilizadas

- Python 3.11
- Flask
- CCXT
- Pandas
- NumPy
- Gunicorn (produção)

## Estrutura do Projeto

```
├── crypto_bot.py     # Lógica principal do bot
├── crypto_web.py     # Servidor web Flask
├── config.py         # Configurações
├── templates/        # Templates HTML
│   └── index.html    # Interface principal
├── static/          # Arquivos estáticos
│   └── css/         # Estilos CSS
├── requirements.txt  # Dependências
└── render.yaml      # Configuração do Render
``` 