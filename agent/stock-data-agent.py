"""
株価データ収集エージェント - AIトレーディングシステム
"""
import json
import boto3
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from mcp_framework import MCPAgent, MCPMessage, MCPBroker

class StockDataAgent(MCPAgent):
    """株価データ収集エージェント"""
    
    def __init__(self, broker: MCPBroker, config: Dict[str, Any]):
        """
        株価データ収集エージェントの初期化
        
        Args:
            broker: MCPブローカー
            config: エージェント設定
        """
        super().__init__(
            agent_id="stock_price_agent",
            broker=broker,
            model_id=config.get("model_id", "amazon.titan-text-express-v1")
        )
        self.target_tickers = config.get("target_tickers", [])
        self.s3_bucket = config.get("s3_bucket", "ai-trading-data")
        self.s3_prefix = config.get("s3_prefix", "stock_data/")
        self.s3_client = boto3.client('s3')
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        メッセージの処理
        データ収集リクエストに対して株価データを収集・保存し、応答する
        """
        if message.message_type == "data_request" and message.content.get("action") == "collect":
            # 収集対象のティッカーがリクエストで指定されていない場合はデフォルト値を使用
            tickers = message.content.get("tickers", self.target_tickers)
            days = message.content.get("days", 30)  # デフォルトは30日分
            
            # 株価データの収集
            market_data = self._collect_stock_data(tickers, days)
            
            # 収集したデータをS3に保存
            self._save_data_to_s3(market_data, message.conversation_id)
            
            # 応答メッセージを作成
            response_content = {
                "status": "success",
                "market_data": {
                    "summary": self._create_data_summary(market_data),
                    "s3_path": f"s3://{self.s3_bucket}/{self.s3_prefix}{message.conversation_id}/",
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            # 応答を返す
            return message.create_response(response_content)
        
        return None
    
    def _collect_stock_data(self, tickers: List[str], days: int) -> Dict[str, Any]:
        """
        指定された銘柄の株価データを収集
        
        Args:
            tickers: 収集対象の銘柄コードリスト
            days: 収集する日数
        
        Returns:
            収集したデータの辞書
        """
        result = {}
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        for ticker in tickers:
            try:
                # yfinanceを使用して株価データを取得
                # 日本株の場合はティッカーに ".T" を追加
                yahoo_ticker = f"{ticker}.T" if len(ticker) == 4 and ticker.isdigit() else ticker
                stock_data = yf.download(yahoo_ticker, start=start_date, end=end_date)
                
                if stock_data.empty:
                    continue
                
                # 各銘柄のデータを整形して保存
                result[ticker] = {
                    "daily_data": self._format_daily_data(stock_data),
                    "metadata": {
                        "ticker": ticker,
                        "company_name": self._get_company_name(ticker),
                        "sector": self._get_sector(ticker),
                        "market": "TSE" if len(ticker) == 4 and ticker.isdigit() else "OTHER"
                    },
                    "technical_indicators": self._calculate_indicators(stock_data)
                }
            except Exception as e:
                print(f"Error collecting data for ticker {ticker}: {str(e)}")
        
        return result
    
    def _format_daily_data(self, stock_data: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        株価データをJSON形式に整形
        """
        daily_data = []
        
        for index, row in stock_data.iterrows():
            daily_data.append({
                "date": index.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "adj_close": float(row["Adj Close"]),
                "volume": int(row["Volume"])
            })
        
        return daily_data
    
    def _calculate_indicators(self, stock_data: pd.DataFrame) -> Dict[str, Any]:
        """
        テクニカル指標を計算
        """
        df = stock_data.copy()
        
        # 移動平均線
        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA50"] = df["Close"].rolling(window=50).mean()
        
        # RSI (Relative Strength Index) - 14日間
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))
        
        # MACD (Moving Average Convergence Divergence)
        df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
        df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = df["EMA12"] - df["EMA26"]
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        
        # ボリンジャーバンド (20日間、標準偏差2)
        df["BB_Middle"] = df["Close"].rolling(window=20).mean()
        std_dev = df["Close"].rolling(window=20).std()
        df["BB_Upper"] = df["BB_Middle"] + (std_dev * 2)
        df["BB_Lower"] = df["BB_Middle"] - (std_dev * 2)
        
        # 最新の指標値を取得
        latest = df.iloc[-1]
        latest_indicators = {
            "moving_averages": {
                "MA5": None if pd.isna(latest["MA5"]) else float(latest["MA5"]),
                "MA20": None if pd.isna(latest["MA20"]) else float(latest["MA20"]),
                "MA50": None if pd.isna(latest["MA50"]) else float(latest["MA50"])
            },
            "rsi": None if pd.isna(latest["RSI"]) else float(latest["RSI"]),
            "macd": {
                "macd_line": None if pd.isna(latest["MACD"]) else float(latest["MACD"]),
                "signal_line": None if pd.isna(latest["Signal"]) else float(latest["Signal"]),
                "histogram": None if pd.isna(latest["MACD"]) or pd.isna(latest["Signal"]) else float(latest["MACD"] - latest["Signal"])
            },
            "bollinger_bands": {
                "upper": None if pd.isna(latest["BB_Upper"]) else float(latest["BB_Upper"]),
                "middle": None if pd.isna(latest["BB_Middle"]) else float(latest["BB_Middle"]),
                "lower": None if pd.isna(latest["BB_Lower"]) else float(latest["BB_Lower"])
            }
        }
        
        # トレンド判定
        latest_indicators["trend"] = self._determine_trend(df)
        
        return latest_indicators
    
    def _determine_trend(self, stock_data: pd.DataFrame) -> str:
        """
        トレンドを判定
        """
        # シンプルなトレンド判定ロジック
        # 20日移動平均線と50日移動平均線を使用
        
        df = stock_data.tail(5)  # 直近5日分のデータ
        
        # 上昇トレンド判定：MA20 > MA50 かつ 直近の終値 > MA20
        if (df["MA20"].iloc[-1] > df["MA50"].iloc[-1] and 
            df["Close"].iloc[-1] > df["MA20"].iloc[-1]):
            return "uptrend"
        
        # 下降トレンド判定：MA20 < MA50 かつ 直近の終値 < MA20
        elif (df["MA20"].iloc[-1] < df["MA50"].iloc[-1] and 
              df["Close"].iloc[-1] < df["MA20"].iloc[-1]):
            return "downtrend"
        
        # それ以外はレンジ相場と判定
        else:
            return "sideways"
    
    def _get_company_name(self, ticker: str) -> str:
        """
        銘柄コードから会社名を取得
        実際の実装では外部APIやデータベースを参照する
        """
        # サンプルの実装（実際にはデータベース等から取得）
        company_names = {
            "7203": "トヨタ自動車",
            "9432": "日本電信電話",
            "9984": "ソフトバンクグループ",
            "6758": "ソニーグループ",
            "6861": "キーエンス",
            # 他の銘柄も必要に応じて追加
        }
        
        return company_names.get(ticker, f"不明企業 ({ticker})")
    
    def _get_sector(self, ticker: str) -> str:
        """
        銘柄コードからセクターを取得
        実際の実装では外部APIやデータベースを参照する
        """
        # サンプルの実装（実際にはデータベース等から取得）
        sectors = {
            "7203": "自動車・輸送機",
            "9432": "情報通信",
            "9984": "情報通信",
            "6758": "電気機器",
            "6861": "電気機器",
            # 他の銘柄も必要に応じて追加
        }
        
        return sectors.get(ticker, "不明")
    
    def _save_data_to_s3(self, market_data: Dict[str, Any], conversation_id: str):
        """
        収集したデータをS3に保存
        """
        # 全体データをJSONとして保存
        self.s3_client.put_object(
            Body=json.dumps(market_data),
            Bucket=self.s3_bucket,
            Key=f"{self.s3_prefix}{conversation_id}/market_data_full.json",
            ContentType="application/json"
        )
        
        # 銘柄ごとにデータを保存
        for ticker, data in market_data.items():
            self.s3_client.put_object(
                Body=json.dumps(data),
                Bucket=self.s3_bucket,
                Key=f"{self.s3_prefix}{conversation_id}/{ticker}.json",
                ContentType="application/json"
            )
    
    def _create_data_summary(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        収集データのサマリーを作成
        """
        summary = {
            "total_tickers": len(market_data),
            "collected_at": datetime.now().isoformat(),
            "ticker_summary": {}
        }
        
        for ticker, data in market_data.items():
            daily_data = data.get("daily_data", [])
            if not daily_data:
                continue
            
            latest_data = daily_data[-1]
            previous_data = daily_data[-2] if len(daily_data) >= 2 else None
            
            # 前日比を計算
            price_change = None
            price_change_percent = None
            if previous_data:
                price_change = latest_data["close"] - previous_data["close"]
                price_change_percent = (price_change / previous_data["close"]) * 100
            
            # 銘柄ごとのサマリー情報
            summary["ticker_summary"][ticker] = {
                "company_name": data.get("metadata", {}).get("company_name", ""),
                "latest_price": latest_data["close"],
                "price_change": price_change,
                "price_change_percent": price_change_percent,
                "volume": latest_data["volume"],
                "date": latest_data["date"],
                "trend": data.get("technical_indicators", {}).get("trend", "unknown")
            }
        
        return summary
