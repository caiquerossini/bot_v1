import ccxt
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime, timedelta
import time
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Union, List, Tuple
import config  # Importa as configurações de email


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
    def __init__(self, atr_period: int = 2, atr_multiplier: float = 1.0, use_close: bool = True):
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
        Inicializa o bot com a Binance
        """
        print("Inicializando bot...")
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        
        self.symbols = [
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
            'LINK/USDT', 'ADA/USDT', 'AAVE/USDT'
        ]
        
        self.timeframes = ['1h', '4h']
        self.signal_history = {
            tf: {symbol: None for symbol in self.symbols} 
            for tf in self.timeframes
        }
        self.last_email_sent = {
            tf: {symbol: {'type': None, 'timestamp': None} for symbol in self.symbols}
            for tf in self.timeframes
        }
        self.chandelier = ChandelierExit(atr_period=2, atr_multiplier=1.0, use_close=True)
        self.heikin_ashi = HeikinAshi()
        self.last_signal_time = {
            tf: {symbol: None for symbol in self.symbols}
            for tf in self.timeframes
        }
        print("Bot inicializado com sucesso!")
        
    def get_historical_data(self, symbol, timeframe='1h', limit=100):
        """
        Obtém dados históricos de preços
        """
        try:
            print(f"Obtendo dados para {symbol}...")
            # Obtém dados de 1h para análise principal
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Obtém dados de 1m para preço atual
            ohlcv_1m = self.exchange.fetch_ohlcv(symbol, '1m', limit=1)
            current_price = ohlcv_1m[0][4] if ohlcv_1m else None
            
            # Ajusta o timestamp para o fuso horário do Brasil (UTC-3)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') - timedelta(hours=3)
            df = df.sort_values('timestamp')
            df = df.reset_index(drop=True)
            
            if current_price:
                df.loc[df.index[-1], 'close'] = current_price
            
            print(f"Dados obtidos com sucesso para {symbol}")
            return df
        except Exception as e:
            print(f"Erro ao obter dados históricos para {symbol}: {e}")
            return None

    def send_email_alert(self, symbol, signal, timeframe):
        """Envia alerta por email apenas se for um novo sinal"""
        try:
            current_time = pd.Timestamp.now()
            
            # Verifica se já enviou email para este tipo de sinal nas últimas 4 horas
            if (self.last_email_sent[timeframe][symbol]['type'] == signal['type'] and 
                self.last_email_sent[timeframe][symbol]['timestamp'] is not None and
                (current_time - self.last_email_sent[timeframe][symbol]['timestamp']).total_seconds() < 14400):
                return
            
            # Verifica se o sinal é o mesmo que o último enviado
            if (self.last_signal_time[timeframe][symbol] is not None and
                signal['type'] == self.signal_history[timeframe][symbol]['type'] and
                (current_time - self.last_signal_time[timeframe][symbol]).total_seconds() < 14400):
                return
            
            email_from = config.EMAIL_FROM
            email_pass = config.EMAIL_PASS
            email_to = config.EMAIL_TO
            
            msg = MIMEMultipart()
            msg['From'] = email_from
            msg['To'] = email_to
            msg['Subject'] = f"Alerta de Trading - {symbol} ({timeframe})"
            
            body = f"""
            Novo sinal detectado para {symbol} ({timeframe}):
            
            Tipo: {signal['type']}
            Preço: {signal['price']:.4f}
            Data/Hora: {signal['timestamp'].strftime('%d/%m/%Y %H:%M:%S')}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(email_from, email_pass)
            server.send_message(msg)
            server.quit()
            
            # Atualiza o controle de emails enviados e último sinal
            self.last_email_sent[timeframe][symbol] = {
                'type': signal['type'],
                'timestamp': current_time
            }
            self.last_signal_time[timeframe][symbol] = current_time
            
            print(f"Email enviado com sucesso para {symbol} ({timeframe})!")
            
        except Exception as e:
            print(f"Erro ao enviar email: {e}")

    def generate_signals(self, df, symbol, timeframe):
        """Gera sinais de trading usando Heikin Ashi e Chandelier Exit"""
        try:
            # Primeiro calcula o Heikin Ashi
            ha_df = self.heikin_ashi.calculate(df)
            
            # Depois aplica o Chandelier Exit nos dados Heikin Ashi
            result = self.chandelier.calculate(ha_df)
            
            # Verifica os últimos sinais
            last_index = result.index[-2]  # Usa o penúltimo candle para evitar sinais incompletos
            
            if result.loc[last_index, 'buy_signal']:
                signal = {
                    'type': 'LONG',
                    'price': float(df.loc[last_index, 'close']),
                    'timestamp': df.loc[last_index, 'timestamp']
                }
                if (self.signal_history[timeframe][symbol] is None or 
                    self.signal_history[timeframe][symbol]['type'] != 'LONG'):
                    self.signal_history[timeframe][symbol] = signal
                    print(f"\nNovo sinal LONG para {symbol} ({timeframe}):")
                    print(f"Preço: {signal['price']:.4f}")
                    print(f"Data/Hora: {signal['timestamp']}")
                    self.send_email_alert(symbol, signal, timeframe)
                    
            elif result.loc[last_index, 'sell_signal']:
                signal = {
                    'type': 'SHORT',
                    'price': float(df.loc[last_index, 'close']),
                    'timestamp': df.loc[last_index, 'timestamp']
                }
                if (self.signal_history[timeframe][symbol] is None or 
                    self.signal_history[timeframe][symbol]['type'] != 'SHORT'):
                    self.signal_history[timeframe][symbol] = signal
                    print(f"\nNovo sinal SHORT para {symbol} ({timeframe}):")
                    print(f"Preço: {signal['price']:.4f}")
                    print(f"Data/Hora: {signal['timestamp']}")
                    self.send_email_alert(symbol, signal, timeframe)
            
            print(f"\nÚltimo sinal para {symbol} ({timeframe}):")
            if self.signal_history[timeframe][symbol]:
                signal = self.signal_history[timeframe][symbol]
                print(f"Tipo: {signal['type']}")
                print(f"Preço: {signal['price']}")
                print(f"Data/Hora: {signal['timestamp']}")
            else:
                print("Nenhum sinal registrado ainda")
                
        except Exception as e:
            print(f"Erro ao gerar sinais para {symbol} ({timeframe}): {e}")

    def run(self):
        """
        Executa o bot em loop contínuo
        """
        print("Iniciando monitoramento das criptomoedas...")
        
        while True:
            try:
                for timeframe in self.timeframes:
                    for symbol in self.symbols:
                        print(f"\nVerificando {symbol} ({timeframe})...")
                        df = self.get_historical_data(symbol, timeframe=timeframe)
                        if df is not None:
                            self.generate_signals(df, symbol, timeframe)
                
                print("\nAguardando 60 segundos para próxima verificação...")
                time.sleep(60)
                
            except Exception as e:
                print(f"Erro durante a execução: {e}")
                time.sleep(60)

if __name__ == "__main__":
    bot = CryptoBot()
    bot.run() 