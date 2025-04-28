import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Union, List, Tuple
import config  # Importa as configurações de email
import logging

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

class HeikinAshi:
    @staticmethod
    def calculate(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula os candles Heikin Ashi
        """
        ha_df = df.copy()
        
        # Cálculo do Heikin Ashi
        ha_df['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
        
        # Primeiro candle
        ha_df.loc[ha_df.index[0], 'ha_open'] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
        
        # Demais candles
        for i in range(1, len(df)):
            ha_df.loc[ha_df.index[i], 'ha_open'] = (ha_df['ha_open'].iloc[i-1] + ha_df['ha_close'].iloc[i-1]) / 2
        
        ha_df['ha_high'] = df[['high', 'open', 'close']].max(axis=1)
        ha_df['ha_low'] = df[['low', 'open', 'close']].min(axis=1)
        
        # Substitui as colunas originais pelos valores Heikin Ashi
        result = df.copy()
        result['open'] = ha_df['ha_open']
        result['high'] = ha_df['ha_high']
        result['low'] = ha_df['ha_low']
        result['close'] = ha_df['ha_close']
        
        return result

class ChandelierExit:
    def __init__(self, atr_period: int = 1, atr_multiplier: float = 0.8, use_close: bool = True):
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.use_close = use_close
        
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        required_columns = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"DataFrame deve conter as colunas {required_columns}")
            
        result = df.copy()
        result['atr'] = self._calculate_atr(result, self.atr_period) * self.atr_multiplier
        
        result['long_stop'] = np.nan
        result['short_stop'] = np.nan
        result['direction'] = 1
        result['buy_signal'] = False
        result['sell_signal'] = False
        
        for i in range(self.atr_period, len(result)):
            if self.use_close:
                highest = result['close'].iloc[i-self.atr_period:i].max()
                lowest = result['close'].iloc[i-self.atr_period:i].min()
            else:
                highest = result['high'].iloc[i-self.atr_period:i].max()
                lowest = result['low'].iloc[i-self.atr_period:i].min()
                
            long_stop = highest - result['atr'].iloc[i]
            short_stop = lowest + result['atr'].iloc[i]
            
            if i > self.atr_period:
                long_stop_prev = result['long_stop'].iloc[i-1]
                if pd.notna(long_stop_prev):
                    if result['close'].iloc[i-1] > long_stop_prev:
                        long_stop = max(long_stop, long_stop_prev)
                        
                short_stop_prev = result['short_stop'].iloc[i-1]
                if pd.notna(short_stop_prev):
                    if result['close'].iloc[i-1] < short_stop_prev:
                        short_stop = min(short_stop, short_stop_prev)
            
            result.loc[result.index[i], 'long_stop'] = long_stop
            result.loc[result.index[i], 'short_stop'] = short_stop
            
            if i > self.atr_period:
                prev_dir = result['direction'].iloc[i-1]
                prev_close = result['close'].iloc[i-1]
                prev_long_stop = result['long_stop'].iloc[i-1]
                prev_short_stop = result['short_stop'].iloc[i-1]
                
                if result['close'].iloc[i] > prev_short_stop:
                    result.loc[result.index[i], 'direction'] = 1
                elif result['close'].iloc[i] < prev_long_stop:
                    result.loc[result.index[i], 'direction'] = -1
                else:
                    result.loc[result.index[i], 'direction'] = prev_dir
                    
                curr_dir = result['direction'].iloc[i]
                
                if curr_dir == 1 and prev_dir == -1:
                    result.loc[result.index[i], 'buy_signal'] = True
                    
                if curr_dir == -1 and prev_dir == 1:
                    result.loc[result.index[i], 'sell_signal'] = True
        
        return result
    
    def _calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr

class CryptoBot:
    def __init__(self):
        """
        Inicializa o bot com a Binance (apenas API pública)
        """
        logger.info("Iniciando inicialização do bot...")
        try:
            # Configuração básica da Binance
            self.exchange = ccxt.binance({
                'enableRateLimit': True
            })
            
            # Define os símbolos e timeframes
            self.symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT', 'SOL/USDT']
            self._timeframes = ['1h', '2h', '1d']
            
            # Inicializa estruturas de dados
            self.signal_history = {timeframe: {} for timeframe in self._timeframes}
            self.sent_emails = {}
            
            # Inicializa indicadores
            self.chandelier = ChandelierExit(atr_period=2, atr_multiplier=1.0, use_close=False)
            self.heikin_ashi = HeikinAshi()
            
            # Testa a conexão
            logger.info("Testando conexão com a Binance...")
            self.exchange.load_markets()
            
            # Testa obtenção de dados
            test_data = self.get_historical_data('BTC/USDT', '1h', 10)
            if test_data is None:
                raise Exception("Falha no teste de obtenção de dados")
                
            logger.info("Bot inicializado com sucesso!")
            logger.info(f"Monitorando {len(self.symbols)} pares: {', '.join(self.symbols)}")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar o bot: {str(e)}")
            raise

    @property
    def timeframes(self):
        return self._timeframes

    @timeframes.setter
    def timeframes(self, value):
        self._timeframes = value
        # Atualiza o histórico de sinais para os novos timeframes
        self.signal_history = {tf: {} for tf in value}

    def get_historical_data(self, symbol, timeframe='1h', limit=100):
        """
        Obtém dados históricos de preços usando apenas API pública
        """
        try:
            logger.info(f"Obtendo dados para {symbol} ({timeframe})")
            
            # Tenta obter os dados com retry simples
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                    
                    if not ohlcv or len(ohlcv) == 0:
                        logger.error(f"Nenhum dado retornado para {symbol}")
                        continue
                    
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df = df.sort_values('timestamp')
                    df = df.reset_index(drop=True)
                    
                    logger.info(f"Dados obtidos com sucesso para {symbol} - {len(df)} registros")
                    return df
                    
                except Exception as e:
                    logger.error(f"Tentativa {attempt + 1}: Erro ao obter dados para {symbol}: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Erro ao obter dados para {symbol}: {str(e)}")
            return None

    def analyze_signals(self, df):
        """
        Analisa todo o gráfico para encontrar sinais
        """
        if len(df) < 3:  # Mínimo de velas necessário
            return None, None

        # 1. Converte para Heikin Ashi
        ha_df = self.heikin_ashi.calculate(df)
        
        # 2. Calcula Chandelier Exit com parâmetros corretos
        ce_df = self.chandelier.calculate(ha_df)

        # 3. Procura sinais em todo o gráfico
        signals = []
        
        # Analisa todas as velas exceto a última
        for i in range(1, len(ce_df)-1):
            current = ce_df.iloc[i]
            prev_candle = ce_df.iloc[i-1]
            
            # Verifica sinal LONG
            if (current['buy_signal'] and 
                current['close'] > prev_candle['high'] and
                current['close'] > current['open']):  # Confirmação adicional
                signals.append({
                    'type': 'LONG',
                    'price': current['close'],
                    'timestamp': df['timestamp'].iloc[i]
                })
            
            # Verifica sinal SHORT
            elif (current['sell_signal'] and 
                  current['close'] < prev_candle['low'] and
                  current['close'] < current['open']):  # Confirmação adicional
                signals.append({
                    'type': 'SHORT',
                    'price': current['close'],
                    'timestamp': df['timestamp'].iloc[i]
                })

        # 4. Verifica se há um novo sinal na última vela
        current_signal = None
        if len(ce_df) >= 2:
            last_candle = ce_df.iloc[-1]
            prev_candle = ce_df.iloc[-2]

            # Novo sinal LONG
            if (last_candle['buy_signal'] and 
                last_candle['close'] > prev_candle['high'] and
                last_candle['close'] > last_candle['open']):
                current_signal = {
                    'type': 'LONG',
                    'price': last_candle['close'],
                    'timestamp': df['timestamp'].iloc[-1]
                }
            
            # Novo sinal SHORT
            elif (last_candle['sell_signal'] and 
                  last_candle['close'] < prev_candle['low'] and
                  last_candle['close'] < last_candle['open']):
                current_signal = {
                    'type': 'SHORT',
                    'price': last_candle['close'],
                    'timestamp': df['timestamp'].iloc[-1]
                }

        # 5. Retorna o sinal atual (se houver) e o último sinal válido
        last_signal = signals[-1] if signals else None
        
        # Se o sinal atual for do mesmo tipo que o último, mantém apenas o atual
        if current_signal and last_signal and current_signal['type'] == last_signal['type']:
            last_signal = None

        return current_signal, last_signal

    def generate_signals(self, df, symbol, timeframe):
        """
        Gera sinais com confirmação e análise histórica
        """
        if df is None or len(df) < 3:
            return
            
        # Analisa os sinais
        current_signal, last_signal = self.analyze_signals(df)
        
        # Se tiver sinal atual, usa ele
        if current_signal:
            self.signal_history[timeframe][symbol] = current_signal
            # Envia email apenas para sinais novos
            if self.is_new_signal(symbol, timeframe, current_signal):
                self.send_signal_email(
                    symbol, 
                    timeframe, 
                    current_signal['type'], 
                    current_signal['price'],
                    last_signal
                )
        # Se não tiver sinal atual mas tiver último sinal, usa o último
        elif last_signal:
            self.signal_history[timeframe][symbol] = last_signal

        # Imprime informações sobre o sinal
        signal_to_show = current_signal or last_signal
        print(f"\nSinal para {symbol} ({timeframe}):")
        if signal_to_show:
            print(f"Tipo: {signal_to_show['type']}")
            print(f"Preço: {signal_to_show['price']:.8f}")
            print(f"Data/Hora: {signal_to_show['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("Nenhum sinal encontrado")

    def is_new_signal(self, symbol, timeframe, current_signal):
        if timeframe not in self.signal_history:
            return True
        if symbol not in self.signal_history[timeframe]:
            return True
        last_signal = self.signal_history[timeframe][symbol]
        if not last_signal:
            return True
        return last_signal['type'] != current_signal['type']

    def send_signal_email(self, symbol, timeframe, signal_type, price, last_signal=None):
        signal_key = f"{symbol}_{timeframe}_{signal_type}"
        
        if signal_key in self.sent_emails:
            return False
            
        try:
            email = config.EMAIL_FROM
            password = config.EMAIL_PASS
            recipient = config.EMAIL_TO
            
            if not all([email, password, recipient]):
                print("Configurações de e-mail ausentes")
                return False
            
            msg = MIMEMultipart()
            msg['From'] = email
            msg['To'] = recipient
            msg['Subject'] = f"Novo Sinal: {symbol} {timeframe} - {signal_type}"
            
            body = f"""
            Novo sinal detectado:
            
            Símbolo: {symbol}
            Timeframe: {timeframe}
            Tipo: {signal_type}
            Preço: {price:.8f}
            Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """

            if last_signal:
                body += f"""
                
                Último sinal anterior:
                Tipo: {last_signal['type']}
                Preço: {last_signal['price']:.8f}
                Data/Hora: {last_signal['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}
                """
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(email, password)
                server.send_message(msg)
            
            self.sent_emails[signal_key] = datetime.now()
            print(f"Email enviado com sucesso para {symbol} ({timeframe})")
            return True
            
        except Exception as e:
            print(f"Erro ao enviar e-mail: {e}")
            return False

    def run(self):
        """
        Executa o bot em loop contínuo
        """
        print("Iniciando monitoramento das criptomoedas...")
        print(f"Símbolos monitorados ({len(self.symbols)}): {', '.join(self.symbols)}")
        
        while True:
            try:
                for timeframe in self.timeframes:
                    print(f"\nAnalisando timeframe {timeframe}:")
                    for symbol in self.symbols:
                        try:
                            print(f"\nVerificando {symbol}...")
                            df = self.get_historical_data(symbol, timeframe=timeframe)
                            if df is not None:
                                self.generate_signals(df, symbol, timeframe)
                            else:
                                print(f"Erro ao obter dados para {symbol}")
                        except Exception as e:
                            print(f"Erro ao processar {symbol}: {e}")
                            continue
                
                print("\nAguardando 60 segundos para próxima verificação...")
                time.sleep(60)
                
            except Exception as e:
                print(f"Erro durante a execução: {e}")
                time.sleep(60)

if __name__ == "__main__":
    bot = CryptoBot()
    bot.run() 