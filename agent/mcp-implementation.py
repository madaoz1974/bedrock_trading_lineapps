"""
Amazon Bedrock MCPフレームワーク - AIトレーディングシステム
"""
import json
import uuid
import boto3
import time
from typing import Dict, List, Any, Optional, Tuple

class MCPMessage:
    """MCPプロトコルのメッセージフォーマット"""
    
    def __init__(self, 
                 sender_id: str, 
                 receiver_id: str, 
                 message_type: str, 
                 content: Dict[str, Any], 
                 conversation_id: Optional[str] = None,
                 reference_id: Optional[str] = None):
        """
        MCPメッセージの初期化
        
        Args:
            sender_id: 送信元エージェントID
            receiver_id: 送信先エージェントID
            message_type: メッセージタイプ (request, response, broadcast, etc.)
            content: メッセージ内容
            conversation_id: 会話ID (Noneの場合は新規生成)
            reference_id: 参照メッセージID (返信時などに使用)
        """
        self.message_id = str(uuid.uuid4())
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.message_type = message_type
        self.content = content
        self.timestamp = time.time()
        self.conversation_id = conversation_id if conversation_id else str(uuid.uuid4())
        self.reference_id = reference_id
    
    def to_dict(self) -> Dict[str, Any]:
        """メッセージをdict形式に変換"""
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "message_type": self.message_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "reference_id": self.reference_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MCPMessage':
        """dict形式からMCPMessageを生成"""
        msg = cls(
            sender_id=data["sender_id"],
            receiver_id=data["receiver_id"],
            message_type=data["message_type"],
            content=data["content"],
            conversation_id=data.get("conversation_id"),
            reference_id=data.get("reference_id")
        )
        msg.message_id = data["message_id"]
        msg.timestamp = data["timestamp"]
        return msg
    
    def create_response(self, content: Dict[str, Any]) -> 'MCPMessage':
        """このメッセージへの応答を作成"""
        return MCPMessage(
            sender_id=self.receiver_id,
            receiver_id=self.sender_id,
            message_type="response",
            content=content,
            conversation_id=self.conversation_id,
            reference_id=self.message_id
        )


class MCPBroker:
    """エージェント間のメッセージングを管理するブローカー"""
    
    def __init__(self, dynamodb_table_name: str = "mcp_messages"):
        """
        MCPブローカーの初期化
        
        Args:
            dynamodb_table_name: メッセージを保存するDynamoDBテーブル名
        """
        self.dynamodb = boto3.resource('dynamodb')
        self.table_name = dynamodb_table_name
        self.table = self.dynamodb.Table(self.table_name)
        self.ensure_table_exists()
        
    def ensure_table_exists(self):
        """テーブルが存在しない場合は作成"""
        try:
            self.dynamodb.meta.client.describe_table(TableName=self.table_name)
        except self.dynamodb.meta.client.exceptions.ResourceNotFoundException:
            self.table = self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {'AttributeName': 'receiver_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'receiver_id', 'AttributeType': 'S'},
                    {'AttributeName': 'timestamp', 'AttributeType': 'N'},
                    {'AttributeName': 'conversation_id', 'AttributeType': 'S'}
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'ConversationIndex',
                        'KeySchema': [
                            {'AttributeName': 'conversation_id', 'KeyType': 'HASH'},
                            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'},
                        'ProvisionedThroughput': {
                            'ReadCapacityUnits': 5,
                            'WriteCapacityUnits': 5
                        }
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            # テーブルが作成されるまで待機
            self.table.meta.client.get_waiter('table_exists').wait(TableName=self.table_name)
    
    def send_message(self, message: MCPMessage) -> str:
        """メッセージの送信と保存"""
        message_dict = message.to_dict()
        self.table.put_item(Item=message_dict)
        return message.message_id
    
    def get_messages(self, agent_id: str, since_timestamp: Optional[float] = None) -> List[MCPMessage]:
        """エージェント宛のメッセージを取得"""
        kwargs = {
            'KeyConditionExpression': boto3.dynamodb.conditions.Key('receiver_id').eq(agent_id)
        }
        
        if since_timestamp:
            kwargs['KeyConditionExpression'] &= boto3.dynamodb.conditions.Key('timestamp').gt(since_timestamp)
        
        response = self.table.query(**kwargs)
        messages = [MCPMessage.from_dict(item) for item in response.get('Items', [])]
        return messages
    
    def get_conversation(self, conversation_id: str) -> List[MCPMessage]:
        """特定の会話のメッセージを全て取得"""
        response = self.table.query(
            IndexName='ConversationIndex',
            KeyConditionExpression=boto3.dynamodb.conditions.Key('conversation_id').eq(conversation_id)
        )
        messages = [MCPMessage.from_dict(item) for item in response.get('Items', [])]
        return sorted(messages, key=lambda m: m.timestamp)
    
    def mark_as_read(self, message_ids: List[str]) -> None:
        """メッセージを既読としてマーク（オプション機能）"""
        # 実装は省略（DynamoDBの項目の更新が必要）
        pass


class MCPAgent:
    """MCP対応エージェントの基本クラス"""
    
    def __init__(self, agent_id: str, broker: MCPBroker, bedrock_client=None, model_id: str = None):
        """
        MCPエージェントの初期化
        
        Args:
            agent_id: エージェントの一意識別子
            broker: メッセージブローカーインスタンス
            bedrock_client: Amazon Bedrockクライアント（必要な場合）
            model_id: 使用するBedrockモデルID（必要な場合）
        """
        self.agent_id = agent_id
        self.broker = broker
        self.bedrock_client = bedrock_client or boto3.client('bedrock-runtime')
        self.model_id = model_id
        self.last_check_timestamp = time.time()
    
    def send_message(self, receiver_id: str, message_type: str, 
                    content: Dict[str, Any], conversation_id: Optional[str] = None,
                    reference_id: Optional[str] = None) -> str:
        """他のエージェントにメッセージを送信"""
        message = MCPMessage(
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            message_type=message_type,
            content=content,
            conversation_id=conversation_id,
            reference_id=reference_id
        )
        return self.broker.send_message(message)
    
    def check_messages(self) -> List[MCPMessage]:
        """自分宛のメッセージを確認"""
        messages = self.broker.get_messages(self.agent_id, self.last_check_timestamp)
        self.last_check_timestamp = time.time()
        return messages
    
    def broadcast(self, receivers: List[str], message_type: str, 
                 content: Dict[str, Any], conversation_id: Optional[str] = None) -> List[str]:
        """複数のエージェントに同じメッセージをブロードキャスト"""
        message_ids = []
        for receiver_id in receivers:
            msg_id = self.send_message(
                receiver_id=receiver_id,
                message_type=message_type,
                content=content,
                conversation_id=conversation_id
            )
            message_ids.append(msg_id)
        return message_ids
    
    def invoke_model(self, prompt: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Amazon Bedrockモデルを呼び出し"""
        if not self.model_id:
            raise ValueError("No model_id specified for this agent")
        
        default_params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 1024
        }
        
        # パラメータの結合（指定されたパラメータを優先）
        if parameters:
            default_params.update(parameters)
        
        # モデルタイプに基づいて適切なリクエスト形式を選択
        if "claude" in self.model_id.lower():
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": default_params["max_tokens"],
                "temperature": default_params["temperature"],
                "top_p": default_params["top_p"],
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
        elif "titan" in self.model_id.lower():
            request_body = {
                "inputText": prompt,
                "textGenerationConfig": {
                    "temperature": default_params["temperature"],
                    "topP": default_params["top_p"],
                    "maxTokenCount": default_params["max_tokens"]
                }
            }
        else:
            raise ValueError(f"Unsupported model type: {self.model_id}")
        
        response = self.bedrock_client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(request_body)
        )
        
        response_body = json.loads(response['body'].read().decode('utf-8'))
        
        # モデルタイプに基づいて適切なレスポンス解析
        if "claude" in self.model_id.lower():
            return {"text": response_body["content"][0]["text"]}
        elif "titan" in self.model_id.lower():
            return {"text": response_body["results"][0]["outputText"]}
        else:
            return response_body
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        メッセージ処理の基本実装
        派生クラスでオーバーライドする必要がある
        """
        raise NotImplementedError("Subclasses must implement process_message()")
    
    def run(self, polling_interval: float = 1.0):
        """
        エージェントのメインループ
        定期的にメッセージをチェックして処理する
        """
        while True:
            messages = self.check_messages()
            for message in messages:
                response = self.process_message(message)
                if response:
                    self.broker.send_message(response)
            
            time.sleep(polling_interval)


class OrchestratorAgent(MCPAgent):
    """中央調整エージェント"""
    
    def __init__(self, broker: MCPBroker, agent_config: Dict[str, Any]):
        """
        中央調整エージェントの初期化
        
        Args:
            broker: メッセージブローカー
            agent_config: エージェント設定情報
        """
        super().__init__(
            agent_id="orchestrator",
            broker=broker,
            model_id=agent_config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        )
        self.data_agents = agent_config.get("data_agents", [])
        self.decision_agents = agent_config.get("decision_agents", [])
        self.execution_agent = agent_config.get("execution_agent")
        self.active_conversations = {}
    
    def start_trading_cycle(self):
        """トレーディングサイクルの開始"""
        # 新しい会話IDを生成
        conversation_id = str(uuid.uuid4())
        self.active_conversations[conversation_id] = {
            "status": "data_collection",
            "data_responses": {},
            "analysis_responses": {},
            "decision_responses": {}
        }
        
        # データ収集エージェントに収集リクエストを送信
        for agent_id in self.data_agents:
            self.send_message(
                receiver_id=agent_id,
                message_type="data_request",
                content={
                    "action": "collect",
                    "timestamp": time.time()
                },
                conversation_id=conversation_id
            )
        
        return conversation_id
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        受信メッセージの処理
        - データ収集の完了確認
        - 分析リクエストの送信
        - 意思決定の統合
        - 取引実行指示
        """
        conversation_id = message.conversation_id
        conv_data = self.active_conversations.get(conversation_id)
        
        if not conv_data:
            # 未知の会話IDの場合、新しいエントリを作成
            self.active_conversations[conversation_id] = {
                "status": "unknown",
                "data_responses": {},
                "analysis_responses": {},
                "decision_responses": {}
            }
            conv_data = self.active_conversations[conversation_id]
        
        # メッセージタイプに基づく処理
        if message.message_type == "data_response":
            # データ収集応答の処理
            conv_data["data_responses"][message.sender_id] = message.content
            
            # 全データ収集エージェントから応答を受け取ったかチェック
            if set(conv_data["data_responses"].keys()) == set(self.data_agents):
                # 分析フェーズへの移行
                conv_data["status"] = "analysis"
                
                # 統合されたデータを作成
                integrated_data = self._integrate_data(conv_data["data_responses"])
                
                # 意思決定エージェントへ分析リクエスト送信
                for agent_id in self.decision_agents:
                    self.send_message(
                        receiver_id=agent_id,
                        message_type="analysis_request",
                        content={
                            "action": "analyze",
                            "data": integrated_data
                        },
                        conversation_id=conversation_id
                    )
        
        elif message.message_type == "analysis_response":
            # 分析応答の処理
            conv_data["analysis_responses"][message.sender_id] = message.content
            
            # 全分析エージェントから応答を受け取ったかチェック
            if set(conv_data["analysis_responses"].keys()) == set(self.decision_agents):
                # 意思決定フェーズへの移行
                conv_data["status"] = "decision"
                
                # 最終的な取引判断
                final_decision = self._make_final_decision(conv_data["analysis_responses"])
                
                # 判断に基づいて取引実行エージェントに指示
                if final_decision["action"] in ["buy", "sell"]:
                    self.send_message(
                        receiver_id=self.execution_agent,
                        message_type="execution_request",
                        content=final_decision,
                        conversation_id=conversation_id
                    )
                else:
                    # アクションが不要な場合はサイクルを終了
                    conv_data["status"] = "completed"
                    # 結果をログに記録
                    self._log_cycle_result(conversation_id, "no_action", final_decision)
        
        elif message.message_type == "execution_response":
            # 取引実行応答の処理
            conv_data["status"] = "completed"
            # 取引結果をログに記録
            execution_result = message.content
            self._log_cycle_result(conversation_id, execution_result["status"], execution_result)
            
            # 学習フィードバックのためのデータを準備
            self._prepare_learning_feedback(conversation_id, execution_result)
        
        # 応答が必要な場合はここで生成して返す
        return None
    
    def _integrate_data(self, data_responses: Dict[str, Any]) -> Dict[str, Any]:
        """
        各データ収集エージェントからのデータを統合
        """
        integrated_data = {
            "market_data": {},
            "news_data": {},
            "policy_data": {},
            "technical_data": {},
            "timestamp": time.time()
        }
        
        # 各エージェントからのデータを対応するセクションに統合
        for agent_id, data in data_responses.items():
            if "stock_price_agent" in agent_id:
                integrated_data["market_data"].update(data.get("market_data", {}))
            elif "news_agent" in agent_id:
                integrated_data["news_data"].update(data.get("news_data", {}))
            elif "policy_agent" in agent_id:
                integrated_data["policy_data"].update(data.get("policy_data", {}))
            elif "technical_agent" in agent_id:
                integrated_data["technical_data"].update(data.get("technical_data", {}))
        
        return integrated_data

    def _make_final_decision(self, analysis_responses: Dict[str, Any]) -> Dict[str, Any]:
        """
        各分析エージェントからの結果を統合して最終判断を行う
        """
        # 各エージェントからの評価をスコア化
        signal_score = analysis_responses.get("signal_agent", {}).get("signal_strength", 0)
        risk_assessment = analysis_responses.get("risk_agent", {}).get("risk_level", "high")
        allocation_percent = analysis_responses.get("allocation_agent", {}).get("allocation_percentage", 0)
        timing_preference = analysis_responses.get("timing_agent", {}).get("optimal_timing", {})
        
        # リスクレベルに基づく閾値調整
        risk_thresholds = {
            "low": 0.3,
            "medium": 0.5,
            "high": 0.7
        }
        
        action_threshold = risk_thresholds.get(risk_assessment, 0.5)
        
        # プロンプトを構築してBedrockモデルに最終判断を依頼
        prompt = f"""
        あなたは高度なAIトレーディングシステムの中央調整エージェントです。
        以下のデータに基づいて最適な取引判断を行ってください。
        
        シグナル強度: {signal_score} (範囲: -1.0〜1.0、正の値は買い、負の値は売り)
        リスク評価: {risk_assessment}
        推奨資金配分: {allocation_percent}%
        最適取引タイミング: {timing_preference}
        
        現在の判断閾値: {action_threshold} (リスクレベルに基づく調整値)
        
        以下の形式で回答してください:
        - 推奨アクション: [buy/sell/hold]
        - 確信度: [0.0〜1.0]
        - 理由: [簡潔な説明]
        - 銘柄コード: [対象銘柄]
        - 数量: [取引数量]
        - 価格条件: [指値/成行/逆指値など]
        """
        
        # Bedrockモデルを呼び出して判断を取得
        response = self.invoke_model(prompt, {
            "temperature": 0.2,  # 低温度で一貫性のある判断を促進
            "max_tokens": 512
        })
        
        # モデル出力をパースして構造化
        model_output = response["text"]
        
        # 出力から情報を抽出 (実際の実装ではより堅牢なパーサーが必要)
        action_match = re.search(r"推奨アクション:\s*(\w+)", model_output)
        confidence_match = re.search(r"確信度:\s*([\d\.]+)", model_output)
        reason_match = re.search(r"理由:\s*(.+?)(?:\n|$)", model_output)
        ticker_match = re.search(r"銘柄コード:\s*(\w+)", model_output)
        quantity_match = re.search(r"数量:\s*(\d+)", model_output)
        price_match = re.search(r"価格条件:\s*(.+?)(?:\n|$)", model_output)
        
        final_decision = {
            "action": action_match.group(1) if action_match else "hold",
            "confidence": float(confidence_match.group(1)) if confidence_match else 0.0,
            "reason": reason_match.group(1) if reason_match else "",
            "ticker": ticker_match.group(1) if ticker_match else "",
            "quantity": int(quantity_match.group(1)) if quantity_match else 0,
            "price_condition": price_match.group(1) if price_match else "market"
        }
        
        # 確信度が閾値以下ならホールド判断に変更
        if final_decision["confidence"] < action_threshold:
            final_decision["action"] = "hold"
        
        return final_decision

    def _log_cycle_result(self, conversation_id: str, status: str, result: Dict[str, Any]):
        """トレーディングサイクルの結果をログに記録"""
        log_entry = {
            "conversation_id": conversation_id,
            "timestamp": time.time(),
            "status": status,
            "result": result,
            "cycle_data": self.active_conversations.get(conversation_id, {})
        }
        
        # DynamoDBにログを保存
        log_table = self.dynamodb.Table("trading_cycle_logs")
        log_table.put_item(Item=log_entry)

    def _prepare_learning_feedback(self, conversation_id: str, execution_result: Dict[str, Any]):
        """取引実行後の学習フィードバックを準備"""
        # 学習用データの集約
        cycle_data = self.active_conversations.get(conversation_id, {})
        
        learning_data = {
            "conversation_id": conversation_id,
            "timestamp": time.time(),
            "data_collected": cycle_data.get("data_responses", {}),
            "analysis_results": cycle_data.get("analysis_responses", {}),
            "final_decision": execution_result,
            "execution_status": execution_result.get("status"),
            "execution_details": execution_result.get("details", {})
        }
        
        # 学習データをS3に保存
        s3_client = boto3.client('s3')
        s3_client.put_object(
            Bucket="ai-trading-learning-data",
            Key=f"feedback/{conversation_id}.json",
            Body=json.dumps(learning_data),
            ContentType="application/json"
        )