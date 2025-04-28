from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for, session
from crypto_bot import CryptoBot
import threading
import time
import pandas as pd
from datetime import datetime, timedelta
import ccxt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
import sys

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__, 
    template_folder='templates',
    static_folder='static'
)
app.secret_key = 'sua_chave_secreta_aqui'  # Troque por uma chave forte em produção

# Variáveis globais para armazenar os dados
signals_data = {
    '1h': {},
    '2h': {},
    '1d': {}
}
last_signals = {}  # Para controlar novos sinais
bot = None  # Será inicializado na função init_bot
last_update_time = None  # Timestamp da última atualização do bot

def init_bot():
    """Inicializa o bot com tratamento de erros"""
    global bot, signals_data
    try:
        logger.info("Iniciando o bot...")
        bot = CryptoBot()
        
        # Inicializa o dicionário de sinais
        for timeframe in bot.timeframes:
            signals_data[timeframe] = {}
            for symbol in bot.symbols:
                signals_data[timeframe][symbol] = {
                    'signal': None,
                    'current_price': None,
                    'current_time': None
                }
                logger.info(f"Inicializado {symbol} para {timeframe}")
        
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar o bot: {str(e)}")
        return False

def ensure_bot_initialized():
    """Garante que o bot está inicializado com várias tentativas"""
    global bot
    if not bot:
        logger.info("Bot não inicializado. Tentando inicializar...")
        max_retries = 3
        retry_delay = 5  # segundos
        
        for attempt in range(max_retries):
            logger.info(f"Tentativa {attempt + 1} de {max_retries}")
            if init_bot():
                return True
            if attempt < max_retries - 1:  # Não espera após a última tentativa
                logger.info(f"Aguardando {retry_delay} segundos antes da próxima tentativa...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Aumenta o tempo de espera entre tentativas
        
        logger.error("Todas as tentativas de inicialização falharam")
        return False
    return True

def bot_thread():
    """Thread para executar o bot em segundo plano"""
    global last_update_time, signals_data
    retry_delay = 60  # Delay inicial entre tentativas

    while True:
        try:
            if not ensure_bot_initialized():
                logger.error(f"Falha ao inicializar o bot na thread. Tentando novamente em {retry_delay} segundos...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)  # Aumenta o delay até no máximo 5 minutos
                continue

            retry_delay = 60  # Reseta o delay após sucesso
            current_time = pd.Timestamp.now()
            last_update_time = current_time
            
            logger.info("Iniciando atualização dos dados...")
            for timeframe in bot.timeframes:
                for symbol in bot.symbols:
                    try:
                        df = bot.get_historical_data(symbol, timeframe=timeframe)
                        if df is not None and len(df) > 0:
                            current_price = float(df['close'].iloc[-1])
                            bot.generate_signals(df, symbol, timeframe)
                            
                            signals_data[timeframe][symbol] = {
                                'signal': bot.signal_history[timeframe].get(symbol),
                                'current_price': current_price,
                                'current_time': current_time
                            }
                            logger.info(f"Dados atualizados: {symbol} ({timeframe}) - Preço: {current_price:.8f}")
                        else:
                            logger.warning(f"Sem dados para {symbol} ({timeframe})")
                    except Exception as e:
                        logger.error(f"Erro ao processar {symbol} ({timeframe}): {str(e)}")
                        continue
                    
                    # Pequena pausa entre chamadas para respeitar rate limits
                    time.sleep(0.5)
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Erro na thread do bot: {str(e)}")
            time.sleep(60)

# Usuário e senha fixos para autenticação simples
def check_login(username, password):
    return username == 'admin' and password == 'admin123'

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if check_login(username, password):
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='Usuário ou senha inválidos.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# Proteger a rota principal
@app.route('/')
def home():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    try:
        if not ensure_bot_initialized():
            return "Erro ao inicializar o bot. Tente novamente.", 500

        # Calcula os segundos restantes até a próxima atualização
        seconds_left = 60
        if last_update_time:
            elapsed = (datetime.now() - last_update_time).total_seconds()
            seconds_left = max(0, 60 - int(elapsed))

        # Processa os sinais para cada timeframe
        processed_signals = {}
        for timeframe in bot.timeframes:
            processed_signals[timeframe] = {}
            for symbol in bot.symbols:
                data = signals_data.get(timeframe, {}).get(symbol, {})
                elapsed_time = ''
                if data.get('signal') and data['signal'].get('timestamp'):
                    time_diff = datetime.now() - data['signal']['timestamp']
                    if time_diff.total_seconds() < 60:
                        elapsed_time = 'Agora'
                    else:
                        elapsed_time = f"{int(time_diff.total_seconds() / 60)}"

                processed_signals[timeframe][symbol] = {
                    'signal': data.get('signal'),
                    'current_price': data.get('current_price'),
                    'elapsed_time': elapsed_time
                }
        
        return render_template('index.html', signals=processed_signals, seconds_left=seconds_left)
    except Exception as e:
        logger.error(f"Erro na rota principal: {str(e)}")
        return f"Erro ao carregar a página: {str(e)}", 500

@app.route('/get_prices')
def get_prices():
    """Rota para obter os preços atualizados via AJAX"""
    try:
        if not ensure_bot_initialized():
            logger.error("Bot não está inicializado")
            return jsonify({'error': 'Bot não inicializado'}), 500
            
        logger.info("Processando requisição get_prices")
        
        # Força atualização dos dados antes de retornar
        current_time = pd.Timestamp.now()
        for timeframe in bot.timeframes:
            for symbol in bot.symbols:
                try:
                    logger.info(f"Obtendo dados para {symbol} ({timeframe})")
                    df = bot.get_historical_data(symbol, timeframe=timeframe)
                    if df is not None and len(df) > 0:
                        current_price = float(df['close'].iloc[-1])
                        bot.generate_signals(df, symbol, timeframe)
                        
                        signals_data[timeframe][symbol] = {
                            'signal': bot.signal_history[timeframe].get(symbol),
                            'current_price': current_price,
                            'current_time': current_time
                        }
                        logger.info(f"Dados atualizados: {symbol} ({timeframe}) - Preço: {current_price:.8f}")
                    else:
                        logger.warning(f"Sem dados para {symbol} ({timeframe})")
                except Exception as e:
                    logger.error(f"Erro ao processar {symbol} ({timeframe}): {str(e)}")
                    continue
                
                # Pequena pausa entre chamadas para respeitar rate limits
                time.sleep(0.1)
        
        # Prepara os dados para retorno
        serialized_data = {
            timeframe: {} for timeframe in bot.timeframes
        }
        
        for timeframe in bot.timeframes:
            logger.info(f"Processando timeframe {timeframe}")
            for symbol, data in signals_data[timeframe].items():
                if data:  # Verifica se há dados para este símbolo
                    signal_data = data.get('signal', {}) or {}
                    current_price = data.get('current_price')
                    
                    if current_price is not None:
                        logger.info(f"Dados encontrados para {symbol}: Preço atual = {current_price}")
                        
                        serialized_data[timeframe][symbol] = {
                            'current_price': float(current_price),
                            'signal': {
                                'type': signal_data.get('type'),
                                'price': float(signal_data.get('price', 0)) if signal_data.get('price') else None,
                                'timestamp': signal_data.get('timestamp').strftime('%Y-%m-%d %H:%M:%S') if signal_data.get('timestamp') else None
                            } if signal_data else None,
                            'current_time': data['current_time'].strftime('%Y-%m-%d %H:%M:%S') if data.get('current_time') else None,
                            'elapsed_time': 'Agora' if signal_data and (datetime.now() - signal_data['timestamp']).total_seconds() < 60 else str(int((datetime.now() - signal_data['timestamp']).total_seconds() / 60)) if signal_data and signal_data.get('timestamp') else None
                        }
                    else:
                        logger.warning(f"Sem preço atual para {symbol}")
        
        # Adiciona status do bot
        serialized_data['bot_status'] = True
        
        # Log do tamanho dos dados
        response_data = jsonify(serialized_data)
        logger.info(f"Tamanho dos dados serializados: {len(str(serialized_data))} bytes")
        logger.info("Dados processados com sucesso")
        
        return response_data
        
    except Exception as e:
        logger.error(f"Erro ao obter preços: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/profile')
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('profile.html')

@app.before_request
def before_request():
    """Executa antes de cada requisição para garantir que o bot está inicializado"""
    if request.endpoint == 'static':
        return  # Permite acesso a arquivos estáticos sem verificação
        
    if request.endpoint != 'login' and not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if request.endpoint not in ['login', 'static']:
        if not ensure_bot_initialized():
            logger.error("Falha ao inicializar o bot antes da requisição")
            return jsonify({'error': 'Falha ao inicializar o bot. Por favor, tente novamente mais tarde.'}), 500

if __name__ == '__main__':
    try:
        # Cria diretórios se não existirem
        os.makedirs('templates', exist_ok=True)
        os.makedirs('static/css', exist_ok=True)
        
        # Inicializa o bot
        if not init_bot():
            logger.error("Falha ao inicializar o bot. Encerrando aplicação.")
            sys.exit(1)

        # Inicia o bot em uma thread separada
        logger.info("Iniciando thread do bot...")
        bot_thread = threading.Thread(target=bot_thread)
        bot_thread.daemon = True
        bot_thread.start()
        
        # Inicia o servidor web
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
            
    except Exception as e:
        logger.error(f"Erro fatal ao iniciar a aplicação: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1) 