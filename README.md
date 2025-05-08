# Amazon Bedrock と MCP を活用した AI トレーディングエージェント開発

Amazon Bedrock と Multi-agent Conversational Protocol (MCP) を活用した日本株のシステムトレードアプリケーション開発について、詳細な設計と実装方針について

## システムアーキテクチャの全体像

まず、全体的なシステムアーキテクチャを設計しましょう。マルチエージェントによる協調的な意思決定モデルを中心に置き、各専門エージェントが連携して動作するシステムを構築します。

## マルチエージェントアーキテクチャの詳細設計

[マルチエージェントアーキテクチャの詳細設計](/doc/architecture-diagram.tsx)

### 各エージェントの役割と責任範囲
MCPフレームワークを活用し、以下のエージェントを配置します。各エージェントはAmazon Bedrockの異なるモデルを活用し、専門性を持たせます。

1. 中央調整エージェント (オーケストレーター)

使用モデル: Claude 3.7 Sonnet (分析力と判断力に優れている)

責任範囲:

- 全体プロセスの管理と調整
- エージェント間の対話促進と情報統合
- 最終的な売買判断の決定
- 継続的な学習と戦略最適化

2. データ収集エージェント群

- 株価データ収集エージェント

使用モデル: Titan  
責任範囲: Yahoo Finance, 日経新聞などからの株価データ取得と整形

- ニュース分析エージェント

使用モデル: Claude 3 Haiku (高速処理に優れている)  
責任範囲: 世界・日本の社会情勢ニュースの収集と分析

- 政策分析エージェント

使用モデル: Claude 3 Opus (詳細な文書理解に優れている)  
責任範囲: 政府発表、総理大臣演説などの政策文書分析

- テクニカル分析エージェント

使用モデル: Titan  
責任範囲: チャートパターン認識、テクニカル指標の計算と分析

3. 意思決定エージェント群

- シグナル生成エージェント

使用モデル: Claude 3.7 Sonnet  
責任範囲: 各種データの統合分析と売買シグナルの生成

- リスク管理エージェント

使用モデル: Claude 3.7 Sonnet  
責任範囲: 市場リスク、個別銘柄リスクの評価と対策

- 資金配分エージェント

使用モデル: Titan  
責任範囲: 最適なポートフォリオ配分と資金管理

- 実行タイミングエージェント

使用モデル: Claude 3 Haiku  
責任範囲: 市場状況に応じた最適な取引タイミングの決定

4. 取引実行エージェント

使用モデル: Titan
責任範囲:

- 立花証券APIとの連携
- 注文管理と執行確認
- エラーハンドリングと再試行ロジック
# AIトレーディングシステムのデプロイと初期テスト手順

AIトレーディングシステムのデプロイから初期テストまでの詳細な手順を説明します。段階的なアプローチで確実にシステムを立ち上げるための方法です。

## 事前準備

### 1. 開発環境のセットアップ

```bash
# 必要なツールのインストール
npm install -g aws-cdk
pip install --upgrade aws-cli
pip install pipenv

# プロジェクトディレクトリの作成
mkdir ai-trading-system
cd ai-trading-system

# CDKプロジェクトの初期化
cdk init app --language typescript

# 依存関係のインストール
npm install aws-cdk-lib constructs source-map-support @types/node
```

### 2. AWSアカウントの設定

```bash
# AWSプロファイルの設定
aws configure

# CDK環境のブートストラップ（初回のみ）
cdk bootstrap aws://ACCOUNT-NUMBER/REGION
```

### 3. システム構成ファイルの準備

- `lib/` ディレクトリに先ほどのスタック定義を保存
- 環境設定ファイルの作成（以下は例）

```bash
# .env ファイルの作成
cat > .env << EOF
BEDROCK_REGION=us-west-2
DAILY_BUDGET_USD=20
SIMULATION_MODE=true
EOF
```

## デプロイ手順

### 1. ソースコードの組織化

```bash
# Lambdaソースディレクトリの作成
mkdir -p lambda/orchestrator
mkdir -p lambda/agents/stock_data
mkdir -p lambda/agents/news
mkdir -p lambda/agents/signal
mkdir -p lambda/agents/execution

# 共通ユーティリティディレクトリ
mkdir -p lambda/common
```

### 2. 各コンポーネントの実装をLambdaディレクトリに配置

```bash
# 例: オーケストレーター実装の配置
cat > lambda/orchestrator/orchestrator.py << EOF
import json
import boto3
import os
import uuid
import time
import datetime
from typing import Dict, List, Any, Optional

# MCPオーケストレーター実装
def handler(event, context):
    """Lambda handler for the orchestrator"""
    action = event.get('action', '')
    conversation_id = event.get('conversationId', str(uuid.uuid4()))
    
    # 処理タイプに基づいたアクション
    if action == 'startDataCollection':
        return start_data_collection(conversation_id)
    elif action == 'checkDataCollection':
        return check_data_collection(conversation_id)
    elif action == 'startAnalysis':
        return start_analysis(conversation_id)
    # その他のアクション実装...
    
    return {
        'statusCode': 400,
        'body': 'Invalid action specified'
    }

# 実装コードは前述のスニペットから移植
EOF

# 他のエージェント実装も同様に配置
```

### 3. 必要なライブラリの準備

```bash
# 各Lambdaディレクトリにrequirements.txtを作成
cat > lambda/orchestrator/requirements.txt << EOF
boto3==1.28.57
pandas==2.1.0
numpy==1.25.2
EOF

# 同様に他のディレクトリにも作成

# Lambda用デプロイパッケージ作成ヘルパースクリプト
cat > build_lambda_layers.sh << EOF
#!/bin/bash
set -e

# 全Lambdaディレクトリ
LAMBDA_DIRS=(
  "lambda/orchestrator"
  "lambda/agents/stock_data"
  "lambda/agents/news"
  "lambda/agents/signal"
  "lambda/agents/execution"
)

for dir in "\${LAMBDA_DIRS[@]}"; do
  echo "Building package for \$dir"
  cd "\$dir"
  
  # Lambda用の仮想環境を作成
  python -m venv .venv
  source .venv/bin/activate
  
  # 依存関係のインストール
  pip install -r requirements.txt
  
  # デプロイパッケージの作成
  mkdir -p python
  pip install -r requirements.txt -t python/
  
  # パッケージングが不要な標準ライブラリの削除
  find python -name "__pycache__" -type d -exec rm -rf {} +
  
  # 仮想環境の終了
  deactivate
  
  cd ../../../
done

echo "All Lambda packages built successfully"
EOF

chmod +x build_lambda_layers.sh
./build_lambda_layers.sh
```

### 4. CDKデプロイ設定の最終確認

```bash
# bin/ai-trading-system.ts の更新
cat > bin/ai-trading-system.ts << EOF
#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { AITradingSystemStack } from '../lib/ai-trading-system-stack';
import * as dotenv from 'dotenv';

// 環境変数の読み込み
dotenv.config();

const app = new cdk.App();
new AITradingSystemStack(app, 'AITradingSystemStack', {
  env: { 
    account: process.env.CDK_DEFAULT_ACCOUNT, 
    region: process.env.CDK_DEFAULT_REGION 
  },
  bedrockRegion: process.env.BEDROCK_REGION || 'us-west-2',
  simulationMode: process.env.SIMULATION_MODE === 'true',
  dailyBudgetUsd: parseFloat(process.env.DAILY_BUDGET_USD || '20')
});
EOF

# dotenvの追加
npm install dotenv
```

### 5. CDKデプロイの実行

```bash
# スタックの合成（問題がないか確認）
cdk synth

# デプロイの実行
cdk deploy --require-approval never
```

## 初期テスト手順

### 1. システム全体の動作テスト

```bash
# Step Functionsステートマシンの実行テスト
AWS_STATE_MACHINE_ARN=$(aws cloudformation describe-stacks --stack-name AITradingSystemStack --query "Stacks[0].Outputs[?OutputKey=='TradingCycleStateMachineArn'].OutputValue" --output text)

aws stepfunctions start-execution \
  --state-machine-arn $AWS_STATE_MACHINE_ARN \
  --input '{"testMode": true}'
```

### 2. 個別エージェントのテスト

```bash
# 株価データエージェントの単体テスト
STOCK_AGENT_FUNCTION=$(aws lambda list-functions --query "Functions[?FunctionName=='AITradingSystemStack-StockDataAgentFunction'].FunctionName" --output text)

aws lambda invoke \
  --function-name $STOCK_AGENT_FUNCTION \
  --payload '{"message_type": "data_request", "content": {"action": "collect", "tickers": ["7203", "9984"]}}' \
  stock_agent_response.json

# レスポンスの確認
cat stock_agent_response.json
```

### 3. シミュレーションテストの実行

シミュレーションモードでのフルサイクルテストを行います：

```bash
# シミュレーション用のユーティリティスクリプト作成
cat > run_simulation.py << EOF
import boto3
import json
import time
import uuid
import datetime

def run_simulation():
    """AIトレーディングシステムのシミュレーションを実行"""
    # Step Functionsクライアント
    sf_client = boto3.client('stepfunctions')
    
    # ステートマシンARNの取得
    cf_client = boto3.client('cloudformation')
    response = cf_client.describe_stacks(StackName='AITradingSystemStack')
    outputs = response['Stacks'][0]['Outputs']
    state_machine_arn = next(output['OutputValue'] for output in outputs if output['OutputKey'] == 'TradingCycleStateMachineArn')
    
    # テスト実行を開始
    execution_id = str(uuid.uuid4())
    response = sf_client.start_execution(
        stateMachineArn=state_machine_arn,
        name=f'simulation-{execution_id}',
        input=json.dumps({
            'testMode': True,
            'tickers': ['7203', '9984', '6758', '9432'],
            'simulationParams': {
                'marketVolatility': 'medium',
                'newsImpact': 'high',
                'runDate': datetime.datetime.now().isoformat()
            }
        })
    )
    
    execution_arn = response['executionArn']
    print(f"Started simulation with execution ARN: {execution_arn}")
    
    # 完了を待機
    while True:
        response = sf_client.describe_execution(executionArn=execution_arn)
        status = response['status']
        
        if status in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
            print(f"Execution completed with status: {status}")
            break
            
        print(f"Execution in progress... Status: {status}")
        time.sleep(10)
    
    # 結果の取得と表示
    if status == 'SUCCEEDED':
        output = json.loads(response['output'])
        print("Simulation results:")
        print(json.dumps(output, indent=2))
        
        # CloudWatchメトリクスの表示
        print("\nChecking CloudWatch metrics...")
        cw_client = boto3.client('cloudwatch')
        metrics = cw_client.list_metrics(
            Namespace='AITrading/BedrockUsage',
            MetricName='TotalCostUSD'
        )
        print(f"Found {len(metrics['Metrics'])} cost metrics")
    
    return status

if __name__ == "__main__":
    run_simulation()
EOF

# シミュレーションの実行
python run_simulation.py
```

### 4. ログとメトリクスの確認

```bash
# CloudWatchダッシュボードURLの取得
DASHBOARD_URL=$(aws cloudformation describe-stacks --stack-name AITradingSystemStack --query "Stacks[0].Outputs[?OutputKey=='DashboardURL'].OutputValue" --output text)

echo "CloudWatch Dashboard URL: $DASHBOARD_URL"

# ログの確認
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/AITradingSystemStack"

# 特定のLambda関数のログを表示
aws logs get-log-events \
  --log-group-name "/aws/lambda/AITradingSystemStack-OrchestratorFunction" \
  --log-stream-name $(aws logs describe-log-streams \
    --log-group-name "/aws/lambda/AITradingSystemStack-OrchestratorFunction" \
    --order-by LastEventTime \
    --descending \
    --limit 1 \
    --query "logStreams[0].logStreamName" \
    --output text)
```

### 5. モニタリングスクリプトの作成

```bash
# リアルタイムモニタリングスクリプト
cat > monitor_system.py << EOF
import boto3
import json
import time
import datetime
import os
from tabulate import tabulate

def monitor_system():
    """AIトレーディングシステムのリアルタイムモニタリング"""
    os.system('clear' if os.name == 'posix' else 'cls')
    
    print("====== AI Trading System Monitor ======")
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================")
    
    # Step Functions実行の確認
    sf_client = boto3.client('stepfunctions')
    cf_client = boto3.client('cloudformation')
    response = cf_client.describe_stacks(StackName='AITradingSystemStack')
    outputs = response['Stacks'][0]['Outputs']
    state_machine_arn = next(output['OutputValue'] for output in outputs if output['OutputKey'] == 'TradingCycleStateMachineArn')
    
    # 実行中のステートマシン
    executions = sf_client.list_executions(
        stateMachineArn=state_machine_arn,
        statusFilter='RUNNING'
    )
    
    print("\n== Active Trading Cycles ==")
    if executions['executions']:
        execution_data = []
        for exec in executions['executions']:
            start_time = exec['startDate'].strftime('%H:%M:%S')
            exec_details = sf_client.describe_execution(executionArn=exec['executionArn'])
            current_state = "Unknown"
            
            try:
                history = sf_client.get_execution_history(
                    executionArn=exec['executionArn'],
                    reverseOrder=True,
                    maxResults=1
                )
                if history['events']:
                    last_event = history['events'][0]
                    if 'stateEnteredEventDetails' in last_event:
                        current_state = last_event['stateEnteredEventDetails']['name']
            except:
                pass
                
            execution_data.append([
                exec['name'],
                start_time,
                current_state,
                exec['executionArn'].split(':')[-1][:8]
            ])
        
        print(tabulate(execution_data, headers=["Name", "Start Time", "Current State", "ID"]))
    else:
        print("No active trading cycles")
    
    # コスト使用状況
    print("\n== Cost Usage (Today) ==")
    cw_client = boto3.client('cloudwatch')
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Bedrockトークン使用量
    model_metrics = []
    metrics = cw_client.list_metrics(
        Namespace='AITrading/BedrockUsage',
        MetricName='TotalCostUSD'
    )
    
    for metric in metrics['Metrics']:
        dimensions = {d['Name']: d['Value'] for d in metric['Dimensions']}
        model_id = dimensions.get('ModelId', 'Unknown')
        
        response = cw_client.get_metric_statistics(
            Namespace='AITrading/BedrockUsage',
            MetricName='TotalCostUSD',
            Dimensions=[{'Name': 'ModelId', 'Value': model_id}],
            StartTime=today,
            EndTime=datetime.datetime.now(),
            Period=86400,
            Statistics=['Sum']
        )
        
        cost = 0
        if response['Datapoints']:
            cost = response['Datapoints'][0]['Sum']
        
        model_metrics.append([model_id, f"${cost:.4f}"])
    
    if model_metrics:
        print(tabulate(model_metrics, headers=["Model", "Cost"]))
    else:
        print("No model usage data available yet")
    
    # Lambda実行回数
    print("\n== Lambda Invocations (Today) ==")
    lambda_client = boto3.client('lambda')
    lambda_functions = lambda_client.list_functions(
        FunctionVersion='ALL',
        MaxItems=50
    )
    
    lambda_metrics = []
    for function in lambda_functions['Functions']:
        if 'AITradingSystemStack' in function['FunctionName']:
            response = cw_client.get_metric_statistics(
                Namespace='AWS/Lambda',
                MetricName='Invocations',
                Dimensions=[{'Name': 'FunctionName', 'Value': function['FunctionName']}],
                StartTime=today,
                EndTime=datetime.datetime.now(),
                Period=86400,
                Statistics=['Sum']
            )
            
            invocations = 0
            if response['Datapoints']:
                invocations = int(response['Datapoints'][0]['Sum'])
            
            # シンプルな名前に変換
            simple_name = function['FunctionName'].replace('AITradingSystemStack-', '').replace('Function', '')
            lambda_metrics.append([simple_name, invocations])
    
    if lambda_metrics:
        print(tabulate(lambda_metrics, headers=["Function", "Invocations"]))
    else:
        print("No Lambda invocation data available yet")
    
    # リフレッシュのためのキープロンプト
    print("\nPress Ctrl+C to exit or wait for refresh...")

if __name__ == "__main__":
    try:
        while True:
            monitor_system()
            time.sleep(30)  # 30秒ごとに更新
    except KeyboardInterrupt:
        print("\nMonitoring stopped")
EOF

# 必要なライブラリのインストール
pip install tabulate boto3

# モニタリングの開始
python monitor_system.py
```

## トラブルシューティングガイド

初期テスト中に発生する可能性のある問題とその解決策：

### 1. デプロイ失敗時の確認

```bash
# スタックデプロイの状態確認
aws cloudformation describe-stack-events --stack-name AITradingSystemStack --max-items 5

# CDKのロールバック
cdk destroy AITradingSystemStack
```

### 2. Lambda関数のテスト失敗

```bash
# Lambda関数のログを確認
LOG_GROUP="/aws/lambda/AITradingSystemStack-StockDataAgentFunction"
aws logs tail $LOG_GROUP --follow

# Lambda関数のテスト環境変数を確認
aws lambda get-function-configuration \
  --function-name AITradingSystemStack-StockDataAgentFunction \
  --query "Environment.Variables"
```

### 3. Bedrockモデルへのアクセス問題

```bash
# IAMポリシーの確認
ROLE_NAME=$(aws cloudformation describe-stack-resources \
  --stack-name AITradingSystemStack \
  --logical-resource-id BedrockAccessRole \
  --query "StackResources[0].PhysicalResourceId" \
  --output text)

aws iam list-attached-role-policies --role-name $ROLE_NAME
```

## 本番デプロイへの移行チェックリスト

初期テストが成功したら、本番環境への移行前に以下を確認します：

1. **シミュレーションモードの無効化**：
   - `.env`ファイルの`SIMULATION_MODE=false`への更新
   - 再デプロイによる変更適用

2. **予算制約の見直し**：
   - シミュレーション期間の実際の使用量を分析
   - 必要に応じて`DAILY_BUDGET_USD`の調整

3. **セキュリティの強化**：
   - IAMロールのアクセス権限の最小化
   - API認証情報の安全な管理
   - CloudTrailによる監査ログの確認

4. **監視アラートの設定**：
   - 異常検知アラートの設定
   - 予算アラートの調整

5. **バックアップとリカバリ計画**：
   - データバックアップ手順の確認
   - 障害発生時の回復手順のテスト

## まとめ

以上の手順に従って、AIトレーディングシステムをAWS環境にデプロイし、初期テストを行うことができます。段階的なテストアプローチにより、システムの挙動を安全に検証し、必要な調整を行った上で本番環境への移行を進めることが可能です。

モニタリングとログ分析を継続的に行いながら、システムのパフォーマンスと費用対効果を最適化していくことが重要です。