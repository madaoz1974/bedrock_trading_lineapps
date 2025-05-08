"""
取引実行エージェント - AIトレーディングシステム
"""
import json
import boto3
import time
import datetime
import hashlib
import hmac
import base64
import requests
import uuid
import logging
from typing import Dict, List, Any, Optional, Tuple

from mcp_framework import MCPAgent, MCPMessage, MCPBroker

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ExecutionAgent')

class TachibanaAPIClient:
    """立花証券APIクライアント"""
    
    def __init__(self, api_key: str, api_secret: str, api_base_url: str):
        """
        立花証券APIクライアントの初期化
        
        Args:
            api_key: APIキー
            api_secret: APIシークレット
            api_base_url: API基本URL
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_base_url = api_base_url
        self.session_token = None
        self.token_expiry = None
    
    def _generate_signature(self, method: str, path: str, timestamp: str, body: str = "") -> str:
        """APIリクエスト用の署名を生成"""
        message = f"{method}{path}{timestamp}{body}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')
    
    def _make_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """APIリクエストを実行"""
        url = f"{self.api_base_url}{path}"
        timestamp = str(int(time.time() * 1000))
        
        body = ""
        if data:
            body = json.dumps(data)
        
        signature = self._generate_signature(method, path, timestamp, body)
        
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature
        }
        
        if self.session_token:
            headers["Authorization"] = f"Bearer {self.session_token}"
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers)
            elif method == "POST":
                response = requests.post(url, headers=headers, data=body)
            elif method == "PUT":
                response = requests.put(url, headers=headers, data=body)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"API request error: {str(e)}")
            raise
    
    def login(self) -> bool:
        """APIにログインしトークンを取得"""
        try:
            response = self._make_request("POST", "/auth/login", {
                "apiKey": self.api_key
            })
            
            if response.get("status") == "success":
                self.session_token = response.get("token")
                # トークンの有効期限（通常は24時間）
                expiry_seconds = response.get("expiresIn", 86400)
                self.token_expiry = time.time() + expiry_seconds
                return True
            else:
                logger.error(f"Login failed: {response.get('message')}")
                return False
        
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False
    
    def ensure_logged_in(self) -> bool:
        """ログイン状態を確認し、必要に応じて再ログイン"""
        if not self.session_token or not self.token_expiry or time.time() > self.token_expiry - 300:
            return self.login()
        return True
    
    def get_account_info(self) -> Dict[str, Any]:
        """口座情報を取得"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        return self._make_request("GET", "/account/info")
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """現在のポジション一覧を取得"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        response = self._make_request("GET", "/positions")
        return response.get("positions", [])
    
    def get_stock_quote(self, ticker: str) -> Dict[str, Any]:
        """株価情報を取得"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        return self._make_request("GET", f"/quotes/{ticker}")
    
    def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """注文を発注"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        return self._make_request("POST", "/orders", order_data)
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """注文状況を取得"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        return self._make_request("GET", f"/orders/{order_id}")
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """注文をキャンセル"""
        if not self.ensure_logged_in():
            raise Exception("Failed to login")
        
        return self._make_request("DELETE", f"/orders/{order_id}")


class ExecutionAgent(MCPAgent):
    """取引実行エージェント"""
    
    def __init__(self, broker: MCPBroker, config: Dict[str, Any]):
        """
        取引実行エージェントの初期化
        
        Args:
            broker: MCPブローカー
            config: エージェント設定
        """
        super().__init__(
            agent_id="execution_agent",
            broker=broker,
            model_id=config.get("model_id", "amazon.titan-text-express-v1")
        )
        
        # 立花証券API設定
        api_key = config.get("tachibana_api_key", "")
        api_secret = config.get("tachibana_api_secret", "")
        api_base_url = config.get("tachibana_api_base_url", "https://api.example-tachibana.com/v1")
        
        self.api_client = TachibanaAPIClient(api_key, api_secret, api_base_url)
        
        # 設定値
        self.simulation_mode = config.get("simulation_mode", True)  # シミュレーションモード（デフォルトは有効）
        self.max_retries = config.get("max_retries", 3)  # 最大リトライ回数
        self.retry_delay = config.get("retry_delay", 2)  # リトライ間隔（秒）
        
        # S3 設定
        self.s3_client = boto3.client('s3')
        self.s3_bucket = config.get("s3_bucket", "ai-trading-data")
        
        # 注文管理
        self.active_orders = {}  # 進行中の注文管理
        
        # DynamoDB 設定
        self.dynamodb = boto3.resource('dynamodb')
        self.orders_table = self.dynamodb.Table(config.get("orders_table", "trading_orders"))
        self.execution_logs_table = self.dynamodb.Table(config.get("execution_logs_table", "execution_logs"))
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        メッセージの処理
        実行リクエストに対して取引を実行し、応答する
        """
        if message.message_type == "execution_request":
            # 取引指示の取得
            execution_request = message.content
            
            # 取引の実行
            execution_result = self._execute_trade(execution_request, message.conversation_id)
            
            # 実行結果のログ記録
            self._log_execution(execution_request, execution_result, message.conversation_id)
            
            # 応答メッセージを作成
            response_content = {
                "status": execution_result.get("status", "error"),
                "details": execution_result,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            # 応答を返す
            return message.create_response(response_content)
        
        return None
    
    def _execute_trade(self, request: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        """
        取引指示を実行
        
        Args:
            request: 取引リクエスト
            conversation_id: 会話ID
        
        Returns:
            実行結果
        """
        action = request.get("action", "hold")
        ticker = request.get("ticker", "")
        quantity = request.get("quantity", 0)
        price_condition = request.get("price_condition", "market")
        limit_price = request.get("limit_price")
        
        # 取引可能かの検証
        validation_result = self._validate_trade_request(request)
        if not validation_result["valid"]:
            return {
                "status": "error",
                "error": "validation_error",
                "message": validation_result["message"],
                "timestamp": datetime.datetime.now().isoformat()
            }
        
        # シミュレーションモードの場合
        if self.simulation_mode:
            return self._simulate_trade(request)
        
        # 実際の取引実行
        try:
            # 現在の口座情報とポジションを取得
            account_info = self.api_client.get_account_info()
            current_positions = self.api_client.get_positions()
            
            # 現在の株価を取得
            quote = self.api_client.get_stock_quote(ticker)
            current_price = quote.get("price", {}).get("current")
            
            if not current_price:
                return {
                    "status": "error",
                    "error": "price_fetch_error",
                    "message": f"Could not fetch current price for {ticker}",
                    "timestamp": datetime.datetime.now().isoformat()
                }
            
            # 注文データの準備
            order_data = {
                "ticker": ticker,
                "quantity": quantity,
                "side": "buy" if action == "buy" else "sell",
                "order_type": "market" if price_condition == "market" else "limit",
                "client_order_id": str(uuid.uuid4())
            }
            
            # 指値注文の場合
            if price_condition == "limit" and limit_price:
                order_data["limit_price"] = limit_price
            
            # 注文の発注
            for attempt in range(self.max_retries):
                try:
                    order_result = self.api_client.place_order(order_data)
                    
                    if order_result.get("status") == "accepted":
                        order_id = order_result.get("order_id")
                        
                        # 注文の状態を確認
                        order_status = self._check_order_completion(order_id)
                        
                        # 注文をDBに保存
                        self._store_order(order_id, request, order_result, conversation_id)
                        
                        return {
                            "status": "success",
                            "order_id": order_id,
                            "order_status": order_status,
                            "execution_price": order_status.get("execution_price"),
                            "timestamp": datetime.datetime.now().isoformat()
                        }
                    else:
                        # 注文が拒否された場合
                        error_message = order_result.get("message", "Unknown error")
                        logger.error(f"Order rejected: {error_message}")
                        
                        if attempt == self.max_retries - 1:
                            return {
                                "status": "error",
                                "error": "order_rejected",
                                "message": error_message,
                                "timestamp": datetime.datetime.now().isoformat()
                            }
                        
                        time.sleep(self.retry_delay)
                
                except Exception as e:
                    logger.error(f"Order placement error (attempt {attempt+1}/{self.max_retries}): {str(e)}")
                    
                    if attempt == self.max_retries - 1:
                        return {
                            "status": "error",
                            "error": "execution_error",
                            "message": str(e),
                            "timestamp": datetime.datetime.now().isoformat()
                        }
                    
                    time.sleep(self.retry_delay)
        
        except Exception as e:
            logger.error(f"Trade execution error: {str(e)}")
            return {
                "status": "error",
                "error": "system_error",
                "message": str(e),
                "timestamp": datetime.datetime.now().isoformat()
            }
    
    def _validate_trade_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        取引リクエストをバリデーション
        
        Args:
            request: 取引リクエスト
        
        Returns:
            バリデーション結果
        """
        action = request.get("action", "hold")
        ticker = request.get("ticker", "")
        quantity = request.get("quantity", 0)
        confidence = request.get("confidence", 0)
        
        # アクションが「hold」の場合は有効（取引なし）
        if action == "hold":
            return {"valid": True}
        
        # 必須フィールドの確認
        if not ticker:
            return {
                "valid": False,
                "message": "Missing ticker symbol"
            }
        
        if not quantity or quantity <= 0:
            return {
                "valid": False,
                "message": "Invalid quantity"
            }
        
        # 信頼度のチェック
        if confidence < 0.4:
            return {
                "valid": False,
                "message": f"Confidence too low: {confidence}"
            }
        
        # シミュレーションモードでない場合は追加のチェック
        if not self.simulation_mode:
            try:
                # 口座残高の確認（買いの場合）
                if action == "buy":
                    account_info = self.api_client.get_account_info()
                    available_cash = account_info.get("cash", {}).get("available", 0)
                    
                    # 現在の株価を取得
                    quote = self.api_client.get_stock_quote(ticker)
                    current_price = quote.get("price", {}).get("current", 0)
                    
                    # 必要な資金
                    required_cash = current_price * quantity
                    
                    if required_cash > available_cash:
                        return {
                            "valid": False,
                            "message": f"Insufficient funds: required {required_cash}, available {available_cash}"
                        }
                
                # 保有株数の確認（売りの場合）
                elif action == "sell":
                    positions = self.api_client.get_positions()
                    
                    # 対象銘柄の保有数を確認
                    ticker_position = next((p for p in positions if p.get("ticker") == ticker), None)
                    
                    if not ticker_position:
                        return {
                            "valid": False,
                            "message": f"No position found for ticker {ticker}"
                        }
                    
                    available_quantity = ticker_position.get("quantity", 0)
                    
                    if quantity > available_quantity:
                        return {
                            "valid": False,
                            "message": f"Insufficient shares: required {quantity}, available {available_quantity}"
                        }
            
            except Exception as e:
                logger.error(f"Validation error: {str(e)}")
                return {
                    "valid": False,
                    "message": f"Validation error: {str(e)}"
                }
        
        return {"valid": True}
    
    def _simulate_trade(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        取引のシミュレーション
        
        Args:
            request: 取引リクエスト
        
        Returns:
            シミュレーション結果
        """
        action = request.get("action", "hold")
        ticker = request.get("ticker", "")
        quantity = request.get("quantity", 0)
        price_condition = request.get("price_condition", "market")
        
        # シミュレーション用の注文ID
        order_id = f"sim-{uuid.uuid4()}"
        
        # シミュレーションのための株価取得（可能であれば実際のAPIから取得）
        try:
            quote = self.api_client.get_stock_quote(ticker)
            current_price = quote.get("price", {}).get("current")
        except:
            # API取得に失敗した場合はダミー価格を使用
            current_price = 1000  # ダミー価格
        
        # シミュレーション結果
        execution_price = current_price
        
        # 指値注文のシミュレーション
        if price_condition == "limit":
            limit_price = request.get("limit_price")
            if limit_price:
                if action == "buy" and limit_price < current_price:
                    # 買い指値が現在価格より低い場合は未約定
                    return {
                        "status": "pending",
                        "message": "Buy limit order price is below current market price",
                        "order_id": order_id,
                        "current_price": current_price,
                        "limit_price": limit_price,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                elif action == "sell" and limit_price > current_price:
                    # 売り指値が現在価格より高い場合は未約定
                    return {
                        "status": "pending",
                        "message": "Sell limit order price is above current market price",
                        "order_id": order_id,
                        "current_price": current_price,
                        "limit_price": limit_price,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                
                execution_price = limit_price
        
        # 成行注文または約定可能な指値注文
        return {
            "status": "success",
            "order_id": order_id,
            "action": action,
            "ticker": ticker,
            "quantity": quantity,
            "execution_price": execution_price,
            "total_amount": execution_price * quantity,
            "simulation": True,
            "timestamp": datetime.datetime.now().isoformat()
        }
    
    def _check_order_completion(self, order_id: str) -> Dict[str, Any]:
        """
        注文の完了状態を確認
        
        Args:
            order_id: 注文ID
        
        Returns:
            注文状態
        """
        max_checks = 5
        check_interval = 2  # 秒
        
        for i in range(max_checks):
            try:
                order_status = self.api_client.get_order_status(order_id)
                status = order_status.get("status")
                
                if status in ["executed", "partially_executed", "canceled", "rejected"]:
                    return order_status
                
                # まだ約定していない場合は待機
                if i < max_checks - 1:
                    time.sleep(check_interval)
            
            except Exception as e:
                logger.error(f"Error checking order status: {str(e)}")
                if i < max_checks - 1:
                    time.sleep(check_interval)
        
        # 最終的な状態を取得
        try:
            return self.api_client.get_order_status(order_id)
        except Exception:
            return {"status": "unknown", "order_id": order_id}
    
    def _store_order(self, order_id: str, request: Dict[str, Any], 
                   result: Dict[str, Any], conversation_id: str):
        """
        注文情報をデータベースに保存
        
        Args:
            order_id: 注文ID
            request: 取引リクエスト
            result: 注文結果
            conversation_id: 会話ID
        """
        try:
            order_item = {
                "order_id": order_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.datetime.now().isoformat(),
                "request": request,
                "result": result,
                "status": result.get("status"),
                "ticker": request.get("ticker"),
                "action": request.get("action"),
                "quantity": request.get("quantity"),
                "price_condition": request.get("price_condition")
            }
            
            self.orders_table.put_item(Item=order_item)
            
            # アクティブな注文リストにも追加
            self.active_orders[order_id] = order_item
        
        except Exception as e:
            logger.error(f"Error storing order: {str(e)}")
    
    def _log_execution(self, request: Dict[str, Any], result: Dict[str, Any], conversation_id: str):
        """
        取引実行結果をログに記録
        
        Args:
            request: 取引リクエスト
            result: 実行結果
            conversation_id: 会話ID
        """
        try:
            log_item = {
                "execution_id": str(uuid.uuid4()),
                "conversation_id": conversation_id,
                "timestamp": datetime.datetime.now().isoformat(),
                "request": request,
                "result": result,
                "simulation_mode": self.simulation_mode
            }
            
            # DynamoDBにログを保存
            self.execution_logs_table.put_item(Item=log_item)
            
            # S3にも詳細ログを保存
            self.s3_client.put_object(
                Body=json.dumps(log_item),
                Bucket=self.s3_bucket,
                Key=f"execution_logs/{conversation_id}/{log_item['execution_id']}.json",
                ContentType="application/json"
            )
        
        except Exception as e:
            logger.error(f"Error logging execution: {str(e)}")
    
    def check_pending_orders(self):
        """
        保留中の注文の状態を定期的に確認
        
        Note:
            このメソッドは別スレッドで定期的に実行することを想定
        """
        for order_id, order_data in list(self.active_orders.items()):
            # シミュレーションモードの注文はスキップ
            if self.simulation_mode and order_id.startswith("sim-"):
                continue
            
            try:
                # 注文状態の確認
                order_status = self.api_client.get_order_status(order_id)
                status = order_status.get("status")
                
                # 状態が変わった場合のみ更新
                if status != order_data.get("status"):
                    logger.info(f"Order {order_id} status changed: {status}")
                    
                    # DynamoDBの注文情報を更新
                    self.orders_table.update_item(
                        Key={"order_id": order_id},
                        UpdateExpression="SET #s = :s, result = :r, updated_at = :t",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={
                            ":s": status,
                            ":r": order_status,
                            ":t": datetime.datetime.now().isoformat()
                        }
                    )
                    
                    # 完了した注文はアクティブリストから削除
                    if status in ["executed", "canceled", "rejected"]:
                        del self.active_orders[order_id]
            
            except Exception as e:
                logger.error(f"Error checking pending order {order_id}: {str(e)}")
