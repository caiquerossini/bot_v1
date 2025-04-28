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
        if not bot:
            logger.error("Falha ao criar instância do bot - retornou None")
            return False
            
        logger.info(f"Bot criado com sucesso. Timeframes: {bot.timeframes}")
        
        # Tenta obter dados iniciais para verificar se o bot está funcionando
        test_symbol = 'BTC/USDT'
        test_timeframe = '1h'
        logger.info(f"Testando obtenção de dados com {test_symbol} ({test_timeframe})")
        
        test_data = bot.get_historical_data(test_symbol, timeframe=test_timeframe)
        if test_data is None or len(test_data) == 0:
            logger.error("Falha ao obter dados de teste do bot")
            return False
            
        logger.info(f"Teste de dados bem sucedido - obtidos {len(test_data)} registros")
        
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
                logger.info(f"Inicializado {symbol} para timeframe {timeframe}")
        
        logger.info("Bot inicializado com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar o bot: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
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
    while True:
        try:
            if not ensure_bot_initialized():
                logger.error("Falha ao inicializar o bot na thread. Tentando novamente em 60 segundos...")
                time.sleep(60)
                continue

            current_time = pd.Timestamp.now()
            last_update_time = current_time
            
            logger.info("Iniciando atualização dos dados...")
            successful_updates = 0
            total_pairs = len(bot.symbols) * len(bot.timeframes)
            
            for timeframe in bot.timeframes:
                logger.info(f"\nProcessando timeframe {timeframe}")
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
                            successful_updates += 1
                            logger.info(f"Dados atualizados com sucesso para {symbol} ({timeframe}) - Preço: {current_price:.8f}")
                        else:
                            logger.warning(f"Sem dados para {symbol} ({timeframe})")
                            # Mantém os dados anteriores se existirem
                            if timeframe in signals_data and symbol in signals_data[timeframe]:
                                logger.info(f"Mantendo dados anteriores para {symbol} ({timeframe})")
                            else:
                                signals_data[timeframe][symbol] = {
                                    'signal': None,
                                    'current_price': None,
                                    'current_time': None
                                }
                    except Exception as e:
                        logger.error(f"Erro ao processar {symbol} ({timeframe}): {str(e)}")
                        import traceback
                        logger.error(traceback.format_exc())
                        continue
            
            logger.info(f"Atualização concluída. {successful_updates}/{total_pairs} pares atualizados com sucesso.")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Erro na thread do bot: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
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
        for timeframe in ['1h', '2h', '1d']:
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
        import traceback
        logger.error(traceback.format_exc())
        return f"Erro ao carregar a página: {str(e)}", 500

@app.route('/get_prices')
def get_prices():
    """Rota para obter os preços atualizados via AJAX"""
    try:
        if not bot:
            logger.error("Bot não está inicializado")
            return jsonify({'error': 'Bot não inicializado'}), 500
            
        logger.info("Processando requisição get_prices")
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
        logger.info("Dados processados com sucesso")
        return jsonify(serialized_data)
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
        logger.info("Tentando inicializar o bot...")
        if not init_bot():
            logger.error("Falha ao inicializar o bot. Tentando novamente em modo de recuperação...")
            time.sleep(5)  # Pequeno delay antes de tentar novamente
            if not init_bot():
                logger.error("Falha definitiva ao inicializar o bot. Encerrando aplicação.")
                sys.exit(1)

        # Inicia o bot em uma thread separada
        logger.info("Iniciando thread do bot...")
        bot_thread = threading.Thread(target=bot_thread)
        bot_thread.daemon = True
        bot_thread.start()
        
        # Inicia o servidor web
        port = int(os.environ.get('PORT', 5000))
        logger.info(f"Iniciando servidor web na porta {port}...")
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Erro fatal ao iniciar a aplicação: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1) 