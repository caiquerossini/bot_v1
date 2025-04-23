from flask import Flask, render_template_string, jsonify
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


app = Flask(__name__)

# Variáveis globais para armazenar os dados
signals_data = {
    '1h': {},
    '4h': {}
}
last_signals = {}  # Para controlar novos sinais
bot = CryptoBot()

# Reordenar os símbolos
bot.symbols = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'LINK/USDT', 'ADA/USDT', 'AAVE/USDT'
]

# HTML template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Monitor de Sinais Crypto</title>
    <meta charset="utf-8">
    <style>
        :root {
            --bg-color: #1a1a1a;
            --card-bg: #2d2d2d;
            --text-color: #e0e0e0;
            --header-color: #ffffff;
            --border-color: #404040;
            --info-bg: #363636;
            --price-box-bg: #404040;
            --positive-color: #4CAF50;
            --negative-color: #f44336;
            --link-color: #64B5F6;
        }
        
        body { 
            font-family: 'Segoe UI', Arial, sans-serif; 
            margin: 0;
            padding: 15px;
            background-color: var(--bg-color);
            color: var(--text-color);
            display: flex;
            flex-direction: row;
            justify-content: center;
            align-items: flex-start;
            min-height: 100vh;
            padding-bottom: 50px;
        }
        .timeframe-section {
            width: 49%;
            position: relative;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .timeframe-section:first-child {
            border-right: 2px solid var(--border-color);
            padding-right: 25px;
            margin-right: 25px;
        }
        .timeframe-section:last-child {
            padding-left: 20px;
        }
        .timeframe-title {
            text-align: center;
            color: var(--header-color);
            font-size: 1.2em;
            margin: 10px 0 20px 0;
            padding: 10px;
            background-color: var(--card-bg);
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
            width: 100%;
        }
        .grid-container {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            width: 100%;
            justify-content: center;
            align-items: start;
        }
        .signal-card {
            border: 1px solid var(--border-color);
            padding: 15px;
            border-radius: 4px;
            background-color: var(--card-bg);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
            margin: 0 auto;
            width: 100%;
            max-width: 220px;
            height: 180px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .long { border-left: 5px solid var(--positive-color); }
        .short { border-left: 5px solid var(--negative-color); }
        .header-info {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
            height: 28px;
        }
        .price-info {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 0;
            padding: 8px;
            background-color: var(--info-bg);
            border-radius: 4px;
            height: 75px;
        }
        .price-box {
            text-align: center;
            padding: 6px;
            border-radius: 4px;
            background-color: var(--price-box-bg);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
            width: 95px;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .price-label {
            font-size: 0.7em;
            color: #888;
            margin-bottom: 4px;
            width: 100%;
            text-align: center;
        }
        .price-value {
            font-size: 0.9em;
            font-weight: bold;
            color: var(--link-color);
            width: 100%;
            text-align: center;
        }
        .signal-info {
            margin-top: 10px;
            padding: 8px;
            background-color: var(--info-bg);
            border-radius: 4px;
            font-size: 0.85em;
            text-align: center;
            height: 45px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        h2 { 
            color: var(--header-color);
            margin: 0;
            font-size: 1em;
            text-align: left;
            flex: 1;
        }
        .timestamp {
            color: #888;
            font-size: 0.85em;
            margin: 0;
            line-height: 1.6;
            width: 100%;
            text-align: center;
        }
        .signal-type {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 0.8em;
            min-width: 45px;
            text-align: center;
        }
        .price-change {
            font-size: 0.75em;
            margin-top: 4px;
            padding: 2px 4px;
            border-radius: 2px;
            display: inline-block;
            width: 100%;
            text-align: center;
        }
        .positive { 
            background-color: rgba(76, 175, 80, 0.2);
            color: var(--positive-color);
        }
        .negative { 
            background-color: rgba(244, 67, 54, 0.2);
            color: var(--negative-color);
        }
        .signal-long {
            background-color: rgba(76, 175, 80, 0.2);
            color: var(--positive-color);
        }
        .signal-short {
            background-color: rgba(244, 67, 54, 0.2);
            color: var(--negative-color);
        }
        .time-container {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background-color: var(--card-bg);
            padding: 8px;
            text-align: center;
            box-shadow: 0 -2px 4px rgba(0, 0, 0, 0.3);
            z-index: 1000;
            height: 40px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .current-time {
            color: var(--text-color);
            font-size: 0.9em;
            margin-bottom: 3px;
        }
        .countdown {
            color: #888;
            font-size: 0.8em;
        }
        @media (max-width: 1600px) {
            .grid-container {
                grid-template-columns: repeat(4, 1fr);
            }
            .signal-card {
                max-width: 265px;
            }
        }
        @media (max-width: 1200px) {
            .grid-container {
                grid-template-columns: repeat(3, 1fr);
            }
            .signal-card {
                max-width: 260px;
            }
        }
        @media (max-width: 768px) {
            .grid-container {
                grid-template-columns: repeat(2, 1fr);
            }
            .signal-card {
                max-width: 250px;
            }
        }
    </style>
    <script>
        let countdown = 60;
        
        function updatePrices() {
            fetch('/get_prices')
                .then(response => response.json())
                .then(data => {
                    Object.keys(data).forEach(timeframe => {
                        Object.keys(data[timeframe]).forEach(symbol => {
                            const card = document.querySelector(`[data-symbol="${symbol}"][data-timeframe="${timeframe}"]`);
                            if (card) {
                                // Atualiza preço atual
                                const priceElement = card.querySelector('.price-value');
                                if (priceElement) {
                                    priceElement.textContent = parseFloat(data[timeframe][symbol].current_price).toFixed(4);
                                }
                                
                                // Atualiza variação percentual se houver sinal
                                if (data[timeframe][symbol].signal) {
                                    const signalPrice = parseFloat(data[timeframe][symbol].signal.price);
                                    const currentPrice = parseFloat(data[timeframe][symbol].current_price);
                                    const priceChange = ((currentPrice - signalPrice) / signalPrice * 100);
                                    const changeElement = card.querySelector('.price-change');
                                    if (changeElement) {
                                        changeElement.textContent = `${priceChange.toFixed(2)}%`;
                                        changeElement.className = `price-change ${priceChange > 0 ? 'positive' : 'negative'}`;
                                    }
                                }
                            }
                        });
                    });
                })
                .catch(error => console.error('Erro ao atualizar preços:', error));
        }

        function updateCountdown() {
            countdown--;
            if (countdown <= 0) {
                countdown = 60;
                updatePrices();
            }
            document.getElementById('countdown').textContent = `Próxima atualização em ${countdown} segundos`;
        }

        function updateCurrentTime() {
            const now = new Date();
            const options = { 
                timeZone: 'America/Sao_Paulo',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            };
            document.getElementById('current-time').textContent = 
                now.toLocaleTimeString('pt-BR', options);
        }

        setInterval(updateCountdown, 1000);
        setInterval(updateCurrentTime, 1000);
        
        window.onload = () => {
            updateCurrentTime();
            updateCountdown();
            updatePrices();
        };
    </script>
</head>
<body>
    {% for timeframe in timeframes %}
    <div class="timeframe-section">
        <h1 class="timeframe-title">Sinais {{ timeframe }}</h1>
        <div class="grid-container">
            {% for symbol, data in signals[timeframe].items() %}
                <div class="signal-card {% if data.signal %}{{ data.signal.type.lower() }}{% endif %}"
                     data-symbol="{{ symbol }}"
                     data-timeframe="{{ timeframe }}"
                     data-current-signal="{% if data.signal %}{{ data.signal.type }}{% else %}none{% endif %}">
                    <div class="header-info">
                        <h2>{{ symbol }}</h2>
                        {% if data.signal %}
                            <span class="signal-type signal-{{ data.signal.type.lower() }}">
                                {{ data.signal.type }}
                            </span>
                        {% endif %}
                    </div>
                    
                    <div class="price-info">
                        <div class="price-box">
                            <div class="price-label">Preço Atual</div>
                            <div class="price-value">{{ "%.4f"|format(data.current_price) }}</div>
                        </div>
                        
                        {% if data.signal %}
                            <div class="price-box">
                                <div class="price-label">Preço do Sinal</div>
                                <div class="price-value">{{ "%.4f"|format(data.signal.price) }}</div>
                                {% set price_change = ((data.current_price - data.signal.price) / data.signal.price * 100) %}
                                <div class="price-change {% if price_change > 0 %}positive{% else %}negative{% endif %}">
                                    {{ "%.2f"|format(price_change) }}%
                                </div>
                            </div>
                        {% endif %}
                    </div>
                    
                    {% if data.signal %}
                        <div class="signal-info">
                            <p class="timestamp">
                                <strong>Sinal:</strong> 
                                {{ data.signal.timestamp.strftime('%H:%M:%S') }}
                            </p>
                            {% set time_diff = ((data.current_time - data.signal.timestamp).total_seconds() / 60)|int %}
                            <p class="timestamp">
                                <strong>Tempo:</strong> 
                                {% if time_diff < 60 %}
                                    {{ time_diff }} min
                                {% else %}
                                    {{ (time_diff / 60)|int }}h{{ time_diff % 60 }}min
                                {% endif %}
                            </p>
                        </div>
                    {% else %}
                        <div class="signal-info">
                            <p>Aguardando sinal...</p>
                        </div>
                    {% endif %}
                </div>
            {% endfor %}
        </div>
    </div>
    {% endfor %}
    <div class="time-container">
        <div class="current-time" id="current-time"></div>
        <div class="countdown" id="countdown">Próxima atualização em 60 segundos</div>
    </div>
</body>
</html>
'''

def bot_thread():
    """Thread para executar o bot em segundo plano"""
    while True:
        try:
            current_time = pd.Timestamp.now()
            for timeframe in bot.timeframes:
                for symbol in bot.symbols:
                    df = bot.get_historical_data(symbol, timeframe=timeframe)
                    if df is not None:
                        current_price = float(df['close'].iloc[-1])
                        bot.generate_signals(df, symbol, timeframe)
                        signals_data[timeframe][symbol] = {
                            'signal': bot.signal_history[timeframe][symbol],
                            'current_price': current_price,
                            'current_time': current_time
                        }
            time.sleep(60)
        except Exception as e:
            print(f"Erro na thread do bot: {e}")
            time.sleep(60)

@app.route('/')
def home():
    """Rota principal que mostra os sinais"""
    # Reordenar os timeframes para 1h aparecer primeiro (esquerda)
    ordered_timeframes = ['1h', '4h']
    return render_template_string(HTML_TEMPLATE, signals=signals_data, timeframes=ordered_timeframes)

@app.route('/get_prices')
def get_prices():
    """Rota para obter os preços atualizados via AJAX"""
    serialized_data = {
        timeframe: {} for timeframe in bot.timeframes
    }
    for timeframe in bot.timeframes:
        for symbol, data in signals_data[timeframe].items():
            if data:  # Verifica se há dados para este símbolo
                serialized_data[timeframe][symbol] = {
                    'current_price': float(data['current_price']),
                    'signal': {
                        'type': data['signal']['type'],
                        'price': float(data['signal']['price']),
                        'timestamp': data['signal']['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                    } if data['signal'] else None,
                    'current_time': data['current_time'].strftime('%Y-%m-%d %H:%M:%S')
                }
    return jsonify(serialized_data)

if __name__ == '__main__':
    # Inicia o bot em uma thread separada
    bot_thread = threading.Thread(target=bot_thread)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Inicia o servidor web
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port) 