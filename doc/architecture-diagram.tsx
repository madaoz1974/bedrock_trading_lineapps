import React from 'react';
import { BarChart, LineChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const ArchitectureDiagram = () => {
  return (
    <div className="flex flex-col items-center p-4 bg-gray-50 rounded-lg">
      <h2 className="text-2xl font-bold mb-6">Amazon Bedrock + MCP AIトレーディングシステムアーキテクチャ</h2>
      
      {/* Main Architecture Diagram */}
      <div className="w-full bg-white p-6 rounded-lg shadow-md mb-8">
        <div className="flex flex-col">
          {/* Data Collection Layer */}
          <div className="flex justify-around mb-6 border-b-2 border-blue-200 pb-4">
            <div className="flex flex-col items-center">
              <div className="bg-blue-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">株価データ収集<br/>エージェント</p>
                <p className="text-xs mt-1">Yahoo Finance, 日経, etc.</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-blue-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">ニュース分析<br/>エージェント</p>
                <p className="text-xs mt-1">世界・日本情勢</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-blue-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">政策分析<br/>エージェント</p>
                <p className="text-xs mt-1">政府発表・総理演説</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-blue-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">テクニカル分析<br/>エージェント</p>
                <p className="text-xs mt-1">チャート・指標分析</p>
              </div>
            </div>
          </div>
          
          {/* Data Storage Layer */}
          <div className="flex justify-center mb-6">
            <div className="bg-yellow-100 p-4 rounded-lg text-center shadow-sm w-3/4">
              <p className="font-semibold">データストレージ</p>
              <p className="text-xs mt-1">Amazon S3 / RDS / DynamoDB</p>
            </div>
          </div>
          
          {/* Core Processing Layer */}
          <div className="flex justify-center mb-6">
            <div className="bg-green-100 p-6 rounded-lg text-center shadow-sm w-4/5">
              <p className="font-bold mb-2">中央調整エージェント</p>
              <p className="text-sm mb-3">Amazon Bedrock (Claude) + MCP Framework</p>
              
              <div className="flex justify-around">
                <div className="bg-white p-2 rounded-md shadow-sm">
                  <p className="font-semibold text-sm">データ統合</p>
                </div>
                <div className="bg-white p-2 rounded-md shadow-sm">
                  <p className="font-semibold text-sm">分析調整</p>
                </div>
                <div className="bg-white p-2 rounded-md shadow-sm">
                  <p className="font-semibold text-sm">意思決定</p>
                </div>
                <div className="bg-white p-2 rounded-md shadow-sm">
                  <p className="font-semibold text-sm">学習最適化</p>
                </div>
              </div>
            </div>
          </div>
          
          {/* Decision Layer */}
          <div className="flex justify-around mb-6 border-t-2 border-b-2 border-green-200 py-4">
            <div className="flex flex-col items-center">
              <div className="bg-green-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">シグナル生成<br/>エージェント</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-green-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">リスク管理<br/>エージェント</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-green-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">資金配分<br/>エージェント</p>
              </div>
            </div>
            <div className="flex flex-col items-center">
              <div className="bg-green-100 p-4 rounded-lg text-center shadow-sm">
                <p className="font-semibold">執行タイミング<br/>エージェント</p>
              </div>
            </div>
          </div>
          
          {/* Execution Layer */}
          <div className="flex justify-center mb-6">
            <div className="bg-red-100 p-4 rounded-lg text-center shadow-sm w-3/5">
              <p className="font-semibold">取引実行エージェント</p>
              <p className="text-xs mt-1">立花証券API連携・注文管理・エラーハンドリング</p>
            </div>
          </div>
          
          {/* Monitoring Layer */}
          <div className="flex justify-center">
            <div className="bg-purple-100 p-4 rounded-lg text-center shadow-sm w-2/3">
              <p className="font-semibold">監視と分析ダッシュボード</p>
              <p className="text-xs mt-1">CloudWatch / QuickSight</p>
            </div>
          </div>
        </div>
      </div>
      
      {/* Agent Communication Flow */}
      <div className="w-full bg-white p-6 rounded-lg shadow-md">
        <h3 className="text-xl font-bold mb-4 text-center">MCPによるエージェント間コミュニケーションフロー</h3>
        <div className="flex flex-col items-center">
          <div className="w-full bg-gray-100 p-4 rounded-lg mb-4 text-sm">
            <pre className="whitespace-pre-wrap">
              1. 中央調整エージェント: データ収集リクエスト発行
              2. 各データ収集エージェント: データ取得・前処理・格納
              3. 中央調整エージェント: 分析リクエスト発行
              4. 各分析エージェント: 専門分析実行・結果共有
              5. 中央調整エージェント: 分析結果統合・意思決定
              6. 取引実行エージェント: 取引指示受け取り・API連携・執行
              7. 全エージェント: 結果フィードバック・学習最適化
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ArchitectureDiagram;