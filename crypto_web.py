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
    global bot
    try:
        logger.info("Iniciando o bot...")
        bot = CryptoBot()
        # Inicializa o dicionário de sinais para todos os símbolos
        for timeframe in bot.timeframes:
            if timeframe not in signals_data:
                signals_data[timeframe] = {}
            for symbol in bot.symbols:
                signals_data[timeframe][symbol] = {
                    'signal': None,
                    'current_price': None,
                    'current_time': None
                }
        logger.info("Bot inicializado com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar o bot: {e}")
        return False

def bot_thread():
    """Thread para executar o bot em segundo plano"""
    global last_update_time
    while True:
        try:
            current_time = pd.Timestamp.now()
            last_update_time = current_time
            for timeframe in bot.timeframes:
                for symbol in bot.symbols:
                    try:
                        logger.info(f"Processando {symbol} ({timeframe})")
                        df = bot.get_historical_data(symbol, timeframe=timeframe)
                        if df is not None:
                            current_price = float(df['close'].iloc[-1])
                            bot.generate_signals(df, symbol, timeframe)
                            signals_data[timeframe][symbol] = {
                                'signal': bot.signal_history[timeframe][symbol],
                                'current_price': current_price,
                                'current_time': current_time
                            }
                        else:
                            logger.warning(f"Sem dados para {symbol} ({timeframe})")
                    except Exception as e:
                        logger.error(f"Erro ao processar {symbol} ({timeframe}): {e}")
                        continue
            time.sleep(60)
        except Exception as e:
            logger.error(f"Erro na thread do bot: {e}")
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
        # Calcula os segundos restantes até a próxima atualização
        seconds_left = 60
        if last_update_time:
            elapsed = (datetime.now() - last_update_time).total_seconds()
            seconds_left = max(0, 60 - int(elapsed))

        # Processa os sinais para cada timeframe
        processed_signals = {}
        for timeframe in ['1h', '2h', '1d']:  # Usando todos os timeframes do bot
            processed_signals[timeframe] = {}
            if timeframe in signals_data:
                for symbol, data in signals_data[timeframe].items():
                    elapsed_time = ''
                    if data['signal'] and data['signal'].get('timestamp'):
                        time_diff = datetime.now() - data['signal']['timestamp']
                        if time_diff.total_seconds() < 60:
                            elapsed_time = 'Agora'
                        else:
                            elapsed_time = f"{int(time_diff.total_seconds() / 60)}"

                    processed_signals[timeframe][symbol] = {
                        'signal': data['signal'],
                        'current_price': data['current_price'],
                        'elapsed_time': elapsed_time
                    }
        
        return render_template('index.html', signals=processed_signals, seconds_left=seconds_left)
    except Exception as e:
        logger.error(f"Erro na rota principal: {e}")
        return f"Erro ao carregar a página: {str(e)}", 500

@app.route('/get_prices')
def get_prices():
    """Rota para obter os preços atualizados via AJAX"""
    try:
        serialized_data = {
            timeframe: {} for timeframe in bot.timeframes
        }
        for timeframe in bot.timeframes:
            for symbol, data in signals_data[timeframe].items():
                if data:  # Verifica se há dados para este símbolo
                    signal_data = data.get('signal', {}) or {}
                    serialized_data[timeframe][symbol] = {
                        'current_price': float(data['current_price']) if data.get('current_price') else None,
                        'signal': {
                            'type': signal_data.get('type'),
                            'price': float(signal_data.get('price', 0)) if signal_data.get('price') else None,
                            'timestamp': signal_data.get('timestamp').strftime('%Y-%m-%d %H:%M:%S') if signal_data.get('timestamp') else None
                        } if signal_data else None,
                        'current_time': data['current_time'].strftime('%Y-%m-%d %H:%M:%S') if data.get('current_time') else None
                    }
        return jsonify(serialized_data)
    except Exception as e:
        logger.error(f"Erro ao obter preços: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/profile')
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('profile.html')

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
        port = 5000
        logger.info(f"Iniciando servidor web na porta {port}...")
        print('>>> Chegou no app.run() <<<')
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Erro fatal ao iniciar a aplicação: {e}")
        print(f"Erro fatal ao iniciar a aplicação: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 