# AWS CDK によるサーバーレスインフラストラクチャの定義
# TypeScriptを使用したCDKスタックの例

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as stepfunctions from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as path from 'path';

export interface AITradingStackProps extends cdk.StackProps {
  bedrockRegion: string;
  simulationMode: boolean;
}

export class AITradingSystemStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AITradingStackProps) {
    super(scope, id, props);

    // S3バケットの作成（データストア用）
    const dataBucket = new s3.Bucket(this, 'AITradingDataBucket', {
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      lifecycleRules: [
        {
          expiration: cdk.Duration.days(365),
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(30)
            },
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90)
            }
          ]
        }
      ]
    });

    // DynamoDBテーブルの作成
    const mcpMessagesTable = new dynamodb.Table(this, 'MCPMessagesTable', {
      partitionKey: { name: 'receiver_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecovery: true,
    });

    // 会話IDによるGSIの追加
    mcpMessagesTable.addGlobalSecondaryIndex({
      indexName: 'ConversationIndex',
      partitionKey: { name: 'conversation_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      projectionType: dynamodb.ProjectionType.ALL
    });

    // トレード注文テーブル
    const tradingOrdersTable = new dynamodb.Table(this, 'TradingOrdersTable', {
      partitionKey: { name: 'order_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecovery: true,
    });

    // 実行ログテーブル
    const executionLogsTable = new dynamodb.Table(this, 'ExecutionLogsTable', {
      partitionKey: { name: 'execution_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // トレーディングサイクルログテーブル
    const tradingCycleLogsTable = new dynamodb.Table(this, 'TradingCycleLogsTable', {
      partitionKey: { name: 'conversation_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // キューの作成（非同期処理用）
    const dataCollectionQueue = new sqs.Queue(this, 'DataCollectionQueue', {
      visibilityTimeout: cdk.Duration.seconds(300),
      retentionPeriod: cdk.Duration.days(1),
    });

    const analysisQueue = new sqs.Queue(this, 'AnalysisQueue', {
      visibilityTimeout: cdk.Duration.seconds(300),
      retentionPeriod: cdk.Duration.days(1),
    });

    const executionQueue = new sqs.Queue(this, 'ExecutionQueue', {
      visibilityTimeout: cdk.Duration.seconds(300),
      retentionPeriod: cdk.Duration.days(1),
    });

    // IAMロールの作成
    const bedrockAccessRole = new iam.Role(this, 'BedrockAccessRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Bedrockへのアクセス権を追加
    bedrockAccessRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          'bedrock:InvokeModel',
          'bedrock:ListFoundationModels',
          'bedrock:GetFoundationModel',
        ],
        resources: [`arn:aws:bedrock:${props.bedrockRegion}::foundation-model/*`],
      })
    );

    // S3アクセス権の追加
    dataBucket.grantReadWrite(bedrockAccessRole);

    // DynamoDBアクセス権の追加
    mcpMessagesTable.grantReadWriteData(bedrockAccessRole);
    tradingOrdersTable.grantReadWriteData(bedrockAccessRole);
    executionLogsTable.grantReadWriteData(bedrockAccessRole);
    tradingCycleLogsTable.grantReadWriteData(bedrockAccessRole);

    // Lambda関数の作成 - オーケストレーター
    const orchestratorFunction = new lambda.Function(this, 'OrchestratorFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'orchestrator.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/orchestrator')),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(300),
      role: bedrockAccessRole,
      environment: {
        MCP_MESSAGES_TABLE: mcpMessagesTable.tableName,
        TRADING_CYCLE_LOGS_TABLE: tradingCycleLogsTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_REGION: props.bedrockRegion,
        SIMULATION_MODE: props.simulationMode.toString(),
        ORCHESTRATOR_MODEL_ID: 'anthropic.claude-3-sonnet-20240229-v1:0',
      }
    });

    // Lambda関数 - データ収集エージェント
    const stockDataAgentFunction = new lambda.Function(this, 'StockDataAgentFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'stock_data_agent.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/agents/stock_data')),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(60),
      role: bedrockAccessRole,
      environment: {
        MCP_MESSAGES_TABLE: mcpMessagesTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_REGION: props.bedrockRegion,
        AGENT_MODEL_ID: 'amazon.titan-text-express-v1',
      }
    });

    // Lambda関数 - ニュース分析エージェント
    const newsAgentFunction = new lambda.Function(this, 'NewsAgentFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'news_agent.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/agents/news')),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(120),
      role: bedrockAccessRole,
      environment: {
        MCP_MESSAGES_TABLE: mcpMessagesTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_REGION: props.bedrockRegion,
        AGENT_MODEL_ID: 'anthropic.claude-3-haiku-20240307-v1:0',
      }
    });

    // Lambda関数 - シグナル生成エージェント
    const signalAgentFunction = new lambda.Function(this, 'SignalAgentFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'signal_agent.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/agents/signal')),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(90),
      role: bedrockAccessRole,
      environment: {
        MCP_MESSAGES_TABLE: mcpMessagesTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_REGION: props.bedrockRegion,
        AGENT_MODEL_ID: 'anthropic.claude-3-sonnet-20240229-v1:0',
      }
    });

    // Lambda関数 - 取引実行エージェント
    const executionAgentFunction = new lambda.Function(this, 'ExecutionAgentFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'execution_agent.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/agents/execution')),
      memorySize: 1024,
      timeout: cdk.Duration.seconds(60),
      role: bedrockAccessRole,
      environment: {
        MCP_MESSAGES_TABLE: mcpMessagesTable.tableName,
        TRADING_ORDERS_TABLE: tradingOrdersTable.tableName,
        EXECUTION_LOGS_TABLE: executionLogsTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_REGION: props.bedrockRegion,
        SIMULATION_MODE: props.simulationMode.toString(),
        AGENT_MODEL_ID: 'amazon.titan-text-express-v1',
      }
    });

    // Step Functions - トレーディングサイクルステートマシン
    const startDataCollection = new tasks.LambdaInvoke(this, 'StartDataCollection', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'startDataCollection',
      }),
    });

    const checkDataCollection = new tasks.LambdaInvoke(this, 'CheckDataCollection', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'checkDataCollection',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    const startAnalysis = new tasks.LambdaInvoke(this, 'StartAnalysis', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'startAnalysis',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    const checkAnalysis = new tasks.LambdaInvoke(this, 'CheckAnalysis', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'checkAnalysis',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    const executeTrading = new tasks.LambdaInvoke(this, 'ExecuteTrading', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'executeTrading',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    const checkExecution = new tasks.LambdaInvoke(this, 'CheckExecution', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'checkExecution',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    const logResults = new tasks.LambdaInvoke(this, 'LogResults', {
      lambdaFunction: orchestratorFunction,
      payload: stepfunctions.TaskInput.fromObject({
        action: 'logResults',
        conversationId: stepfunctions.JsonPath.stringAt('$.Payload.conversationId'),
      }),
    });

    // データ収集の待機ロジック
    const waitForDataCollection = new stepfunctions.Wait(this, 'WaitForDataCollection', {
      time: stepfunctions.WaitTime.duration(cdk.Duration.seconds(10)),
    });

    const isDataCollectionComplete = new stepfunctions.Choice(this, 'IsDataCollectionComplete')
      .when(stepfunctions.Condition.booleanEquals('$.Payload.isComplete', true), startAnalysis)
      .otherwise(waitForDataCollection);

    // 分析の待機ロジック
    const waitForAnalysis = new stepfunctions.Wait(this, 'WaitForAnalysis', {
      time: stepfunctions.WaitTime.duration(cdk.Duration.seconds(10)),
    });

    const isAnalysisComplete = new stepfunctions.Choice(this, 'IsAnalysisComplete')
      .when(stepfunctions.Condition.booleanEquals('$.Payload.isComplete', true), executeTrading)
      .otherwise(waitForAnalysis);

    // 実行の待機ロジック
    const waitForExecution = new stepfunctions.Wait(this, 'WaitForExecution', {
      time: stepfunctions.WaitTime.duration(cdk.Duration.seconds(10)),
    });

    const isExecutionComplete = new stepfunctions.Choice(this, 'IsExecutionComplete')
      .when(stepfunctions.Condition.booleanEquals('$.Payload.isComplete', true), logResults)
      .otherwise(waitForExecution);

    // ステートマシンの定義
    const definition = startDataCollection
      .next(waitForDataCollection)
      .next(checkDataCollection)
      .next(isDataCollectionComplete)
      .next(startAnalysis)
      .next(waitForAnalysis)
      .next(checkAnalysis)
      .next(isAnalysisComplete)
      .next(executeTrading)
      .next(waitForExecution)
      .next(checkExecution)
      .next(isExecutionComplete)
      .next(logResults);

    // ステートマシンの作成
    const tradingCycleStateMachine = new stepfunctions.StateMachine(this, 'TradingCycleStateMachine', {
      definition,
      timeout: cdk.Duration.minutes(30),
      logs: {
        destination: new logs.LogGroup(this, 'TradingCycleStateMachineLogs', {
          retention: logs.RetentionDays.ONE_WEEK,
        }),
        level: stepfunctions.LogLevel.ALL,
      },
    });

    // スケジュールイベントの作成 (毎日午前9時に実行)
    const dailyTradingRule = new events.Rule(this, 'DailyTradingRule', {
      schedule: events.Schedule.cron({ minute: '0', hour: '9', weekDay: '1-5' }),
    });

    dailyTradingRule.addTarget(new targets.SfnStateMachine(tradingCycleStateMachine));

    // CloudWatch ダッシュボードの作成
    const dashboard = new cloudwatch.Dashboard(this, 'AITradingDashboard', {
      dashboardName: 'AITradingSystem-Dashboard',
    });

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Lambda Executions',
        left: [
          orchestratorFunction.metricInvocations(),
          stockDataAgentFunction.metricInvocations(),
          newsAgentFunction.metricInvocations(),
          signalAgentFunction.metricInvocations(),
          executionAgentFunction.metricInvocations(),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda Errors',
        left: [
          orchestratorFunction.metricErrors(),
          stockDataAgentFunction.metricErrors(),
          newsAgentFunction.metricErrors(),
          signalAgentFunction.metricErrors(),
          executionAgentFunction.metricErrors(),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'Step Functions Executions',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/States',
            metricName: 'ExecutionsStarted',
            dimensionsMap: {
              StateMachineArn: tradingCycleStateMachine.stateMachineArn,
            },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/States',
            metricName: 'ExecutionsSucceeded',
            dimensionsMap: {
              StateMachineArn: tradingCycleStateMachine.stateMachineArn,
            },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/States',
            metricName: 'ExecutionsFailed',
            dimensionsMap: {
              StateMachineArn: tradingCycleStateMachine.stateMachineArn,
            },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
          }),
        ],
      }),
    );

    // 出力値の定義
    new cdk.CfnOutput(this, 'DataBucketName', {
      value: dataBucket.bucketName,
      description: 'Name of the S3 bucket used for storing trading data',
    });

    new cdk.CfnOutput(this, 'MCPMessagesTableName', {
      value: mcpMessagesTable.tableName,
      description: 'Name of the DynamoDB table used for MCP messages',
    });

    new cdk.CfnOutput(this, 'TradingCycleStateMachineArn', {
      value: tradingCycleStateMachine.stateMachineArn,
      description: 'ARN of the Step Functions state machine for trading cycles',
    });

    new cdk.CfnOutput(this, 'DashboardURL', {
      value: `https://${props.env?.region}.console.aws.amazon.com/cloudwatch/home?region=${props.env?.region}#dashboards:name=AITradingSystem-Dashboard`,
      description: 'URL of the CloudWatch dashboard',
    });
  }
}