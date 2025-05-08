"""
シグナル生成エージェント - AIトレーディングシステム
"""
import json
import boto3
import time
import datetime
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple

from mcp_framework import MCPAgent, MCPMessage, MCPBroker

class SignalGenerationAgent(MCPAgent):
    """シグナル生成エージェント"""
    
    def __init__(self, broker: MCPBroker, config: Dict[str, Any]):
        """
        シグナル生成エージェントの初期化
        
        Args:
            broker: MCPブローカー
            config: エージェント設定
        """
        super().__init__(
            agent_id="signal_generation_agent",
            broker=broker,
            model_id=config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        )
        self.s3_client = boto3.client('s3')
        self.s3_bucket = config.get("s3_bucket", "ai-trading-data")
        self.signal_thresholds = config.get("signal_thresholds", {
            "very_strong_buy": 0.8,
            "strong_buy": 0.6,
            "buy": 0.4,
            "neutral": 0.0,
            "sell": -0.4,
            "strong_sell": -0.6,
            "very_strong_sell": -0.8
        })
        self.weight_config = config.get("weight_config", {
"technical": 0.4,
            "fundamental": 0.2, 
            "news": 0.3,
            "policy": 0.1
        })
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        メッセージの処理
        分析リクエストに対してシグナルを生成し、応答する
        """
        if message.message_type == "analysis_request" and message.content.get("action") == "analyze":
            # 統合データの取得
            integrated_data = message.content.get("data", {})
            
            # シグナル生成
            signal_data = self._generate_signals(integrated_data, message.conversation_id)
            
            # シグナルデータをS3に保存
            self._save_data_to_s3(signal_data, message.conversation_id)
            
            # 応答メッセージを作成
            response_content = {
                "status": "success",
                "signal_strength": signal_data.get("aggregate_signal", {}).get("signal_value", 0),
                "signal_type": signal_data.get("aggregate_signal", {}).get("signal_type", "neutral"),
                "confidence": signal_data.get("aggregate_signal", {}).get("confidence", 0),
                "timestamp": datetime.datetime.now().isoformat(),
                "tickers": signal_data.get("ticker_signals", {}),
                "explanation": signal_data.get("explanation", "")
            }
            
            # 応答を返す
            return message.create_response(response_content)
        
        return None
    
    def _generate_signals(self, integrated_data: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        """
        統合データからトレーディングシグナルを生成
        
        Args:
            integrated_data: 統合されたデータ
            conversation_id: 会話ID (データ取得に使用)
        
        Returns:
            生成されたシグナルデータ
        """
        # 各データソースから信号を抽出
        technical_signals = self._analyze_technical_data(integrated_data.get("technical_data", {}))
        news_signals = self._analyze_news_data(integrated_data.get("news_data", {}), conversation_id)
        market_signals = self._analyze_market_data(integrated_data.get("market_data", {}))
        policy_signals = self._analyze_policy_data(integrated_data.get("policy_data", {}), conversation_id)
        
        # 銘柄ごとの信号を生成
        ticker_signals = {}
        all_tickers = set()
        
        # 各ソースのティッカーを収集
        for signals in [technical_signals, news_signals, market_signals]:
            all_tickers.update(signals.keys())
        
        # 銘柄ごとに信号を統合
        for ticker in all_tickers:
            tech_signal = technical_signals.get(ticker, {"signal": 0, "confidence": 0})
            news_signal = news_signals.get(ticker, {"signal": 0, "confidence": 0})
            market_signal = market_signals.get(ticker, {"signal": 0, "confidence": 0})
            policy_signal = policy_signals.get("general", {"signal": 0, "confidence": 0})  # 政策シグナルは一般的に適用
            
            # 重み付き平均を計算
            weighted_signal = (
                tech_signal["signal"] * self.weight_config["technical"] * tech_signal["confidence"] +
                market_signal["signal"] * self.weight_config["fundamental"] * market_signal["confidence"] +
                news_signal["signal"] * self.weight_config["news"] * news_signal["confidence"] +
                policy_signal["signal"] * self.weight_config["policy"] * policy_signal["confidence"]
            )
            
            # 信頼度の重み付き平均
            confidence_sum = (
                self.weight_config["technical"] * tech_signal["confidence"] +
                self.weight_config["fundamental"] * market_signal["confidence"] +
                self.weight_config["news"] * news_signal["confidence"] +
                self.weight_config["policy"] * policy_signal["confidence"]
            )
            
            # 信頼度で正規化
            if confidence_sum > 0:
                final_signal = weighted_signal / confidence_sum
            else:
                final_signal = 0
            
            # 各ソースの寄与度
            contributions = {
                "technical": tech_signal["signal"] * self.weight_config["technical"] * tech_signal["confidence"] / max(1, confidence_sum),
                "fundamental": market_signal["signal"] * self.weight_config["fundamental"] * market_signal["confidence"] / max(1, confidence_sum),
                "news": news_signal["signal"] * self.weight_config["news"] * news_signal["confidence"] / max(1, confidence_sum),
                "policy": policy_signal["signal"] * self.weight_config["policy"] * policy_signal["confidence"] / max(1, confidence_sum)
            }
            
            # シグナルタイプの判定
            signal_type = self._determine_signal_type(final_signal)
            
            ticker_signals[ticker] = {
                "signal_value": final_signal,
                "signal_type": signal_type,
                "confidence": confidence_sum,
                "components": {
                    "technical": tech_signal,
                    "news": news_signal,
                    "market": market_signal,
                    "policy": policy_signal
                },
                "contributions": contributions
            }
        
        # 総合シグナルの生成（ポートフォリオ全体またはインデックスに対して）
        # 簡易版: 個別銘柄シグナルの平均
        if ticker_signals:
            all_signals = [data["signal_value"] for ticker, data in ticker_signals.items()]
            all_confidences = [data["confidence"] for ticker, data in ticker_signals.items()]
            
            avg_signal = sum(all_signals) / len(all_signals)
            avg_confidence = sum(all_confidences) / len(all_confidences)
            
            aggregate_signal = {
                "signal_value": avg_signal,
                "signal_type": self._determine_signal_type(avg_signal),
                "confidence": avg_confidence
            }
        else:
            aggregate_signal = {
                "signal_value": 0,
                "signal_type": "neutral",
                "confidence": 0
            }
        
        # Bedrockモデルを用いた分析結果の解釈と説明生成
        explanation = self._generate_explanation(ticker_signals, aggregate_signal, integrated_data)
        
        return {
            "ticker_signals": ticker_signals,
            "aggregate_signal": aggregate_signal,
            "explanation": explanation,
            "timestamp": datetime.datetime.now().isoformat()
        }
    
    def _analyze_technical_data(self, technical_data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """
        テクニカル指標データを分析してシグナルを生成
        
        Args:
            technical_data: テクニカル指標データ
        
        Returns:
            銘柄ごとのシグナル値と信頼度
        """
        signals = {}
        
        for ticker, data in technical_data.items():
            # 各種テクニカル指標の取得
            ma_data = data.get("moving_averages", {})
            rsi = data.get("rsi")
            macd_data = data.get("macd", {})
            bb_data = data.get("bollinger_bands", {})
            trend = data.get("trend")
            
            # 欠損値チェック
            if not ma_data or rsi is None or not macd_data or not bb_data:
                signals[ticker] = {"signal": 0, "confidence": 0.1}
                continue
            
            # 移動平均線シグナル (-1.0 ~ 1.0)
            ma_signal = 0
            ma_count = 0
            
            # MA5 > MA20 > MA50 なら強い上昇トレンド
            if (ma_data.get("MA5") and ma_data.get("MA20") and ma_data.get("MA50") and
                ma_data["MA5"] > ma_data["MA20"] > ma_data["MA50"]):
                ma_signal = 1.0
                ma_count += 1
            # MA5 < MA20 < MA50 なら強い下降トレンド
            elif (ma_data.get("MA5") and ma_data.get("MA20") and ma_data.get("MA50") and
                  ma_data["MA5"] < ma_data["MA20"] < ma_data["MA50"]):
                ma_signal = -1.0
                ma_count += 1
            # MA5 > MA20 なら弱い上昇トレンド
            elif ma_data.get("MA5") and ma_data.get("MA20") and ma_data["MA5"] > ma_data["MA20"]:
                ma_signal = 0.5
                ma_count += 1
            # MA5 < MA20 なら弱い下降トレンド
            elif ma_data.get("MA5") and ma_data.get("MA20") and ma_data["MA5"] < ma_data["MA20"]:
                ma_signal = -0.5
                ma_count += 1
            
            # RSIシグナル (-1.0 ~ 1.0)
            rsi_signal = 0
            if rsi is not None:
                if rsi > 70:  # 買われすぎ
                    rsi_signal = -0.8
                elif rsi < 30:  # 売られすぎ
                    rsi_signal = 0.8
                elif rsi > 60:  # やや買われすぎ
                    rsi_signal = -0.4
                elif rsi < 40:  # やや売られすぎ
                    rsi_signal = 0.4
            
            # MACDシグナル (-1.0 ~ 1.0)
            macd_signal = 0
            if (macd_data.get("macd_line") is not None and 
                macd_data.get("signal_line") is not None and 
                macd_data.get("histogram") is not None):
                
                # MACDラインがシグナルラインを上回る（ゴールデンクロス）
                if macd_data["macd_line"] > macd_data["signal_line"] and macd_data["histogram"] > 0:
                    macd_signal = 0.7
                # MACDラインがシグナルラインを下回る（デッドクロス）
                elif macd_data["macd_line"] < macd_data["signal_line"] and macd_data["histogram"] < 0:
                    macd_signal = -0.7
                # ヒストグラムが増加中
                elif macd_data["histogram"] > 0:
                    macd_signal = 0.3
                # ヒストグラムが減少中
                elif macd_data["histogram"] < 0:
                    macd_signal = -0.3
            
            # ボリンジャーバンドシグナル (-1.0 ~ 1.0)
            bb_signal = 0
            if (bb_data.get("upper") is not None and 
                bb_data.get("middle") is not None and 
                bb_data.get("lower") is not None):
                
                # 価格データが必要
                price = data.get("current_price")
                if price:
                    # 下限バンドに接近/下回る（買いシグナル）
                    if price <= bb_data["lower"] * 1.01:
                        bb_signal = 0.8
                    # 上限バンドに接近/上回る（売りシグナル）
                    elif price >= bb_data["upper"] * 0.99:
                        bb_signal = -0.8
                    # 中央バンドを下から上に抜ける（弱い買いシグナル）
                    elif price > bb_data["middle"] and price < bb_data["upper"]:
                        bb_signal = 0.4
                    # 中央バンドを上から下に抜ける（弱い売りシグナル）
                    elif price < bb_data["middle"] and price > bb_data["lower"]:
                        bb_signal = -0.4
            
            # トレンド評価 (-0.5 ~ 0.5)
            trend_signal = 0
            if trend == "uptrend":
                trend_signal = 0.5
            elif trend == "downtrend":
                trend_signal = -0.5
            
            # 総合シグナルの計算（加重平均）
            weights = {
                "ma": 0.3,
                "rsi": 0.2,
                "macd": 0.3,
                "bb": 0.1,
                "trend": 0.1
            }
            
            total_signal = (
                ma_signal * weights["ma"] +
                rsi_signal * weights["rsi"] +
                macd_signal * weights["macd"] +
                bb_signal * weights["bb"] +
                trend_signal * weights["trend"]
            )
            
            # 信頼度の計算（データの完全性に基づく）
            confidence = 0.5  # デフォルト値
            
            # データが揃っているほど信頼度が高い
            data_completeness = 0
            if ma_count > 0:
                data_completeness += 0.2
            if rsi is not None:
                data_completeness += 0.2
            if macd_data.get("macd_line") is not None:
                data_completeness += 0.2
            if bb_data.get("upper") is not None:
                data_completeness += 0.2
            if trend is not None:
                data_completeness += 0.2
            
            confidence = max(0.3, data_completeness)
            
            signals[ticker] = {
                "signal": total_signal,
                "confidence": confidence,
                "components": {
                    "ma_signal": ma_signal,
                    "rsi_signal": rsi_signal,
                    "macd_signal": macd_signal,
                    "bb_signal": bb_signal,
                    "trend_signal": trend_signal
                }
            }
        
        return signals
    
    def _analyze_news_data(self, news_data: Dict[str, Any], conversation_id: str) -> Dict[str, Dict[str, float]]:
        """
        ニュースデータを分析してシグナルを生成
        
        Args:
            news_data: ニュースデータ
            conversation_id: 会話ID (S3からのデータ取得に使用)
        
        Returns:
            銘柄ごとのシグナル値と信頼度
        """
        signals = {}
        
        # ニュースデータの概要情報
        news_summary = news_data.get("summary", {})
        
        # ニュースデータの詳細をS3から取得
        try:
            s3_path = news_data.get("s3_path", "")
            if s3_path:
                bucket_name = self.s3_bucket
                key = f"news_data/{conversation_id}/news_categorized.json"
                
                response = self.s3_client.get_object(Bucket=bucket_name, Key=key)
                categorized_news = json.loads(response['Body'].read().decode('utf-8'))
            else:
                # S3パスがない場合はサマリーデータのみを使用
                categorized_news = {"by_impact": {}, "by_category": {}}
        except Exception as e:
            print(f"Error retrieving news data from S3: {str(e)}")
            categorized_news = {"by_impact": {}, "by_category": {}}
        
        # 重要ニュースの取得
        important_news = news_summary.get("important_news", [])
        
        # ポジティブ/ネガティブニュースのカウント
        positive_count = len(categorized_news.get("by_impact", {}).get("positive", []))
        negative_count = len(categorized_news.get("by_impact", {}).get("negative", []))
        total_count = positive_count + negative_count + len(categorized_news.get("by_impact", {}).get("neutral", []))
        
        # 全体的なセンチメントスコアの計算
        if total_count > 0:
            sentiment_score = (positive_count - negative_count) / total_count
        else:
            sentiment_score = 0
        
        # 重要ニュースに基づく銘柄別シグナル生成
        affected_tickers = {}
        
        for news in important_news:
            affected_sectors = news.get("affected_sectors", [])
            impact_direction = news.get("impact_direction", "neutral")
            impact_strength = news.get("impact_strength", 0) / 10.0  # 0-10 スケールを 0-1 に変換
            
            impact_value = 0
            if impact_direction == "positive":
                impact_value = impact_strength
            elif impact_direction == "negative":
                impact_value = -impact_strength
            
            # セクターに属する全銘柄に影響を適用（実際の実装ではセクター→銘柄のマッピングが必要）
            for sector in affected_sectors:
                # セクターに属する銘柄を取得（この例ではダミーデータ）
                sector_tickers = self._get_tickers_for_sector(sector)
                
                for ticker in sector_tickers:
                    if ticker not in affected_tickers:
                        affected_tickers[ticker] = []
                    
                    affected_tickers[ticker].append({
                        "impact": impact_value,
                        "source": news.get("title", "Unknown news")
                    })
        
        # 銘柄ごとのシグナルを計算
        default_tickers = ["7203", "9432", "9984", "6758", "6861"]  # デフォルト銘柄
        
        for ticker in set(list(affected_tickers.keys()) + default_tickers):
            ticker_impacts = affected_tickers.get(ticker, [])
            
            # 銘柄固有のニュース影響がある場合
            if ticker_impacts:
                # 各ニュースの影響の平均
                ticker_signal = sum(item["impact"] for item in ticker_impacts) / len(ticker_impacts)
                # 影響ニュースが多いほど信頼度が高い
                confidence = min(0.8, 0.4 + (len(ticker_impacts) * 0.1))
            else:
                # 銘柄固有のニュースがない場合は全体的なセンチメントを適用
                ticker_signal = sentiment_score * 0.5  # 全体センチメントは影響を半減
                confidence = 0.3
            
            signals[ticker] = {
                "signal": ticker_signal,
                "confidence": confidence,
                "news_count": len(ticker_impacts),
                "sentiment_score": sentiment_score
            }
        
        return signals
    
    def _analyze_market_data(self, market_data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """
        市場データを分析してシグナルを生成（基本的なファンダメンタル分析）
        
        Args:
            market_data: 市場データ
        
        Returns:
            銘柄ごとのシグナル値と信頼度
        """
        signals = {}
        ticker_summary = market_data.get("summary", {}).get("ticker_summary", {})
        
        for ticker, summary in ticker_summary.items():
            # 価格変動の取得
            price_change_percent = summary.get("price_change_percent")
            volume = summary.get("volume", 0)
            trend = summary.get("trend", "unknown")
            
            # シグナルの初期化
            signal_value = 0
            confidence = 0.4  # デフォルト値
            
            # 価格変動に基づくシグナル
            if price_change_percent is not None:
                if price_change_percent > 5:  # 5%以上の上昇
                    signal_value += 0.6  # 強い買いシグナル（モメンタム）
                elif price_change_percent > 2:  # 2-5%の上昇
                    signal_value += 0.3  # 弱い買いシグナル
                elif price_change_percent < -5:  # 5%以上の下落
                    signal_value -= 0.6  # 強い売りシグナル
                elif price_change_percent < -2:  # 2-5%の下落
                    signal_value -= 0.3  # 弱い売りシグナル
                
                # 価格変動の大きさに基づいて信頼度を調整
                if abs(price_change_percent) > 3:
                    confidence += 0.1
            
            # トレンドに基づく追加シグナル
            if trend == "uptrend":
                signal_value += 0.2
                confidence += 0.1
            elif trend == "downtrend":
                signal_value -= 0.2
                confidence += 0.1
            
            # 出来高が大きいほど信頼度が高い（相対的な出来高評価が必要）
            # この例では単純化のため絶対値で判断
            if volume > 1000000:  # 100万株以上
                confidence += 0.1
            
            # シグナル値を範囲内に収める
            signal_value = max(-1.0, min(1.0, signal_value))
            confidence = max(0.2, min(0.9, confidence))
            
            signals[ticker] = {
                "signal": signal_value,
                "confidence": confidence,
                "price_change": price_change_percent,
                "volume": volume,
                "trend": trend
            }
        
        return signals
    
    def _analyze_policy_data(self, policy_data: Dict[str, Any], conversation_id: str) -> Dict[str, Dict[str, float]]:
        """
        政策データを分析してシグナルを生成
        
        Args:
            policy_data: 政策データ
            conversation_id: 会話ID
        
        Returns:
            政策カテゴリごとのシグナル値と信頼度
        """
        # 政策データはすべての銘柄に一般的に適用されるシグナルを生成
        signals = {}
        
        # 政策影響の評価
        policy_summary = policy_data.get("summary", {})
        policy_changes = policy_data.get("recent_changes", [])
        
        # 政策変更の影響評価
        if policy_changes:
            # 最も重要な政策変更を特定
            important_policies = sorted(
                policy_changes, 
                key=lambda x: x.get("importance", 0), 
                reverse=True
            )[:3]  # 上位3つの重要政策
            
            # 政策の方向性評価
            policy_directions = [p.get("market_direction", "neutral") for p in important_policies]
            positive_count = policy_directions.count("positive")
            negative_count = policy_directions.count("negative")
            
            # 政策シグナルの計算
            if positive_count > negative_count:
                signal_value = 0.4  # 弱い買いシグナル
            elif negative_count > positive_count:
                signal_value = -0.4  # 弱い売りシグナル
            else:
                signal_value = 0.0  # 中立
            
            # 政策の重要度に基づく信頼度
            avg_importance = sum(p.get("importance", 0) for p in important_policies) / len(important_policies)
            confidence = min(0.7, 0.3 + (avg_importance / 10.0))  # 0.3〜0.7の範囲
        else:
            # 政策変更がない場合
            signal_value = 0.0
            confidence = 0.2
        
        # 一般的な市場への影響
        signals["general"] = {
            "signal": signal_value,
            "confidence": confidence,
            "policy_count": len(policy_changes)
        }
        
        # 特定のセクターへの影響（政策が特定のセクターに対して影響がある場合）
        sector_impacts = policy_summary.get("sector_impacts", {})
        
        for sector, impact in sector_impacts.items():
            impact_value = impact.get("impact_value", 0)
            impact_confidence = impact.get("confidence", 0.5)
            
            signals[f"sector_{sector}"] = {
                "signal": impact_value,
                "confidence": impact_confidence,
                "sector": sector
            }
        
        return signals
    
    def _determine_signal_type(self, signal_value: float) -> str:
        """
        シグナル値からシグナルタイプを判定
        
        Args:
            signal_value: シグナル値 (-1.0〜1.0)
        
        Returns:
            シグナルタイプ
        """
        thresholds = self.signal_thresholds
        
        if signal_value >= thresholds["very_strong_buy"]:
            return "very_strong_buy"
        elif signal_value >= thresholds["strong_buy"]:
            return "strong_buy"
        elif signal_value >= thresholds["buy"]:
            return "buy"
        elif signal_value > thresholds["neutral"] and signal_value < thresholds["buy"]:
            return "weak_buy"
        elif signal_value < thresholds["neutral"] and signal_value > thresholds["sell"]:
            return "weak_sell"
        elif signal_value <= thresholds["sell"]:
            return "sell"
        elif signal_value <= thresholds["strong_sell"]:
            return "strong_sell"
        elif signal_value <= thresholds["very_strong_sell"]:
            return "very_strong_sell"
        else:
            return "neutral"
    
    def _get_tickers_for_sector(self, sector: str) -> List[str]:
        """
        セクター名から所属銘柄リストを取得
        実際の実装ではデータベースや外部APIを使用
        
        Args:
            sector: セクター名
        
        Returns:
            銘柄コードのリスト
        """
        # サンプル実装（実際にはデータベース等から取得）
        sector_tickers = {
            "自動車・輸送機": ["7203", "7267", "7269", "7201", "7261"],
            "情報通信": ["9432", "9984", "4689", "9613", "9433"],
            "電気機器": ["6758", "6501", "6502", "6594", "6702"],
            "医薬品": ["4502", "4503", "4506", "4507", "4519"],
            "銀行業": ["8306", "8316", "8411", "8601", "8604"],
            # 他のセクターも必要に応じて追加
        }
        
        # 英語名のマッピング
        english_sector_map = {
            "automotive": "自動車・輸送機",
            "telecom": "情報通信",
            "electronics": "電気機器",
            "pharmaceuticals": "医薬品",
            "banking": "銀行業"
        }
        
        # 英語名で検索された場合の対応
        if sector.lower() in english_sector_map:
            japanese_sector = english_sector_map[sector.lower()]
            return sector_tickers.get(japanese_sector, [])
        
        return sector_tickers.get(sector, [])
    
    def _generate_explanation(self, ticker_signals: Dict[str, Dict[str, Any]], 
                            aggregate_signal: Dict[str, Any], 
                            integrated_data: Dict[str, Any]) -> str:
        """
        シグナル生成の説明を生成
        
        Args:
            ticker_signals: 銘柄ごとのシグナルデータ
            aggregate_signal: 総合シグナルデータ
            integrated_data: 統合データ
        
        Returns:
            説明文
        """
        # Bedrockモデルへのプロンプト作成
        prompt = """
        あなたは高度なAIトレーディングシステムのシグナル生成エージェントです。
        複数のデータソースから統合されたシグナルデータに基づいて、トレーディング判断の説明を生成してください。
        
        ### 総合シグナル情報:
        - シグナル値: {aggregate_signal_value}
        - シグナルタイプ: {aggregate_signal_type}
        - 信頼度: {aggregate_confidence}
        
        ### 個別銘柄シグナル:
        {ticker_signals_summary}
        
        ### ニュース分析概要:
        {news_summary}
        
        ### テクニカル分析概要:
        {technical_summary}
        
        ### 以下の点を盛り込んだ分析説明を作成してください:
        1. 現在の市場状況と全体的なシグナルの概要
        2. 特に注目すべき銘柄とその理由
        3. 各データソース（テクニカル、ニュース、ファンダメンタル）からの主要な洞察
        4. シグナルの確信度と潜在的なリスク要因
        5. 短期・中期の見通し
        
        回答は明確で簡潔な日本語で、200-300字程度にまとめてください。
        """
        
        # テンプレート変数の置換
        ticker_signals_summary = ""
# テンプレート変数の置換
        ticker_signals_summary = ""
        for ticker, data in list(ticker_signals.items())[:5]:  # 上位5銘柄のみ表示
            signal_type = data.get("signal_type", "neutral")
            signal_value = data.get("signal_value", 0)
            confidence = data.get("confidence", 0)
            
            ticker_signals_summary += f"- {ticker}: シグナル={signal_value:.2f}, タイプ={signal_type}, 信頼度={confidence:.2f}\n"
        
        # ニュースサマリー
        news_summary = ""
        news_data = integrated_data.get("news_data", {}).get("summary", {})
        if news_data:
            impact_distribution = news_data.get("impact_distribution", {})
            important_news = news_data.get("important_news", [])
            
            news_summary = f"- 全記事数: {news_data.get('total_articles', 0)}\n"
            news_summary += f"- ポジティブ記事: {impact_distribution.get('positive', 0)}, ネガティブ記事: {impact_distribution.get('negative', 0)}\n"
            
            if important_news:
                news_summary += "- 重要ニュース:\n"
                for news in important_news[:2]:  # 上位2件のみ
                    news_summary += f"  * {news.get('title', '不明')}: {news.get('impact_direction', 'neutral')}, 強度={news.get('impact_strength', 0)}\n"
        
        # テクニカル分析サマリー
        technical_summary = ""
        tickers_with_signals = [ticker for ticker, data in ticker_signals.items() 
                               if abs(data.get("components", {}).get("technical", {}).get("signal", 0)) > 0.5]
        
        if tickers_with_signals:
            technical_summary = "- 強いテクニカルシグナルを示す銘柄:\n"
            for ticker in tickers_with_signals[:3]:  # 上位3件のみ
                signal = ticker_signals[ticker].get("components", {}).get("technical", {})
                technical_summary += f"  * {ticker}: シグナル={signal.get('signal', 0):.2f}\n"
        
        # 変数の置換
        filled_prompt = prompt.format(
            aggregate_signal_value=aggregate_signal.get("signal_value", 0),
            aggregate_signal_type=aggregate_signal.get("signal_type", "neutral"),
            aggregate_confidence=aggregate_signal.get("confidence", 0),
            ticker_signals_summary=ticker_signals_summary,
            news_summary=news_summary,
            technical_summary=technical_summary
        )
        
        # Bedrockモデルを呼び出して説明を生成
        try:
            response = self.invoke_model(filled_prompt, {
                "temperature": 0.7,
                "max_tokens": 512
            })
            
            explanation = response.get("text", "")
            return explanation
        except Exception as e:
            print(f"Error generating explanation: {str(e)}")
            return "システムはシグナル分析に基づき、現在の市場状況に対する判断を示しています。詳細な分析結果は個別のシグナルデータを参照してください。"
    
    def _save_data_to_s3(self, signal_data: Dict[str, Any], conversation_id: str):
        """
        生成したシグナルデータをS3に保存
        
        Args:
            signal_data: シグナルデータ
            conversation_id: 会話ID
        """
        try:
            self.s3_client.put_object(
                Body=json.dumps(signal_data),
                Bucket=self.s3_bucket,
                Key=f"signals/{conversation_id}/signal_data.json",
                ContentType="application/json"
            )
        except Exception as e:
            print(f"Error saving signal data to S3: {str(e)}")