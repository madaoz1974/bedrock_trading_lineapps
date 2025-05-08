"""
ニュース分析エージェント - AIトレーディングシステム
"""
import json
import boto3
import requests
from bs4 import BeautifulSoup
import datetime
from typing import Dict, List, Any, Optional, Tuple
import re

from mcp_framework import MCPAgent, MCPMessage, MCPBroker

class NewsAnalysisAgent(MCPAgent):
    """ニュース分析エージェント"""
    
    def __init__(self, broker: MCPBroker, config: Dict[str, Any]):
        """
        ニュース分析エージェントの初期化
        
        Args:
            broker: MCPブローカー
            config: エージェント設定
        """
        super().__init__(
            agent_id="news_analysis_agent",
            broker=broker,
            model_id=config.get("model_id", "anthropic.claude-3-haiku-20240307-v1:0")
        )
        self.news_sources = config.get("news_sources", [
            {"name": "日経新聞", "url": "https://www.nikkei.com/"},
            {"name": "ロイター（日本）", "url": "https://jp.reuters.com/"},
            {"name": "Bloomberg（日本）", "url": "https://www.bloomberg.co.jp/"},
            {"name": "CNBC（日本）", "url": "https://www.cnbc.com/japan/"}
        ])
        self.target_companies = config.get("target_companies", [])
        self.target_keywords = config.get("target_keywords", [
            "日銀", "金融政策", "利上げ", "利下げ", "インフレ", "デフレ", 
            "GDP", "経済指標", "失業率", "為替", "円高", "円安"
        ])
        self.s3_bucket = config.get("s3_bucket", "ai-trading-data")
        self.s3_prefix = config.get("s3_prefix", "news_data/")
        self.s3_client = boto3.client('s3')
        self.comprehend_client = boto3.client('comprehend')
    
    def process_message(self, message: MCPMessage) -> Optional[MCPMessage]:
        """
        メッセージの処理
        データ収集リクエストに対してニュースを収集・分析し、応答する
        """
        if message.message_type == "data_request" and message.content.get("action") == "collect":
            # 追加のキーワードがリクエストにあれば取得
            additional_keywords = message.content.get("keywords", [])
            keywords = list(set(self.target_keywords + additional_keywords))
            
            # 追加の企業があれば取得
            additional_companies = message.content.get("companies", [])
            companies = list(set(self.target_companies + additional_companies))
            
            # ニュースの収集と分析
            news_data = self._collect_and_analyze_news(keywords, companies)
            
            # 収集したデータをS3に保存
            self._save_data_to_s3(news_data, message.conversation_id)
            
            # 応答メッセージを作成
            response_content = {
                "status": "success",
                "news_data": {
                    "summary": self._create_news_summary(news_data),
                    "s3_path": f"s3://{self.s3_bucket}/{self.s3_prefix}{message.conversation_id}/",
                    "timestamp": datetime.datetime.now().isoformat()
                }
            }
            
            # 応答を返す
            return message.create_response(response_content)
        
        return None
    
    def _collect_and_analyze_news(self, keywords: List[str], companies: List[str]) -> Dict[str, Any]:
        """
        ニュースを収集して分析
        
        Args:
            keywords: 検索キーワードリスト
            companies: 対象企業リスト
        
        Returns:
            分析済みニュースデータ
        """
        news_articles = []
        
        # 各ニュースソースからの記事収集
        for source in self.news_sources:
            try:
                source_articles = self._scrape_news_from_source(source, keywords, companies)
                news_articles.extend(source_articles)
            except Exception as e:
                print(f"Error scraping news from {source['name']}: {str(e)}")
        
        # 収集した記事を分析
        analyzed_news = self._analyze_news_articles(news_articles)
        
        # カテゴリ別・影響別に整理
        categorized_news = self._categorize_news(analyzed_news)
        
        return {
            "raw_articles": news_articles,
            "analyzed_articles": analyzed_news,
            "categorized_news": categorized_news,
            "timestamp": datetime.datetime.now().isoformat()
        }
    
    def _scrape_news_from_source(self, source: Dict[str, str], 
                               keywords: List[str], companies: List[str]) -> List[Dict[str, Any]]:
        """
        特定のニュースソースから記事を収集
        
        Args:
            source: ニュースソース情報
            keywords: 検索キーワード
            companies: 対象企業
        
        Returns:
            収集した記事リスト
        """
        collected_articles = []
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(source["url"], headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # ニュースサイトごとの記事抽出ロジック
            # 注: 実際の実装では各ニュースサイトのHTMLに応じたセレクタを設定する必要があります
            if "nikkei.com" in source["url"]:
                articles = self._extract_nikkei_articles(soup)
            elif "reuters.com" in source["url"]:
                articles = self._extract_reuters_articles(soup)
            elif "bloomberg.co.jp" in source["url"]:
                articles = self._extract_bloomberg_articles(soup)
            elif "cnbc.com" in source["url"]:
                articles = self._extract_cnbc_articles(soup)
            else:
                # 汎用的な記事抽出
                articles = self._extract_generic_articles(soup)
            
            # キーワードと企業名でフィルタリング
            for article in articles:
                if self._is_relevant_article(article, keywords, companies):
                    article["source"] = source["name"]
                    collected_articles.append(article)
        
        except Exception as e:
            print(f"Error in _scrape_news_from_source for {source['name']}: {str(e)}")
        
        return collected_articles
    
    def _extract_nikkei_articles(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """日経新聞から記事を抽出"""
        articles = []
        
        # 日経のHTMLパターンに合わせた抽出ロジック
        # これは実際のHTMLに合わせて調整が必要
        for article_element in soup.select('div.k-card'):
            try:
                title_element = article_element.select_one('h3.k-card__headline')
                link_element = article_element.select_one('a')
                summary_element = article_element.select_one('div.k-card__excerpt')
                date_element = article_element.select_one('time.k-card__time')
                
                if title_element and link_element:
                    title = title_element.text.strip()
                    url = link_element.get('href')
                    if not url.startswith('http'):
                        url = f"https://www.nikkei.com{url}"
                    
                    summary = ""
                    if summary_element:
                        summary = summary_element.text.strip()
                    
                    published_date = datetime.datetime.now().isoformat()
                    if date_element:
                        try:
                            date_text = date_element.text.strip()
                            # 日付フォーマットの解析
                            published_date = self._parse_japanese_date(date_text)
                        except:
                            pass
                    
articles.append({
                        "title": title,
                        "url": url,
                        "summary": summary,
                        "published_date": published_date,
                        "content": ""  # 本文はURLから別途取得
                    })
            except Exception as e:
                print(f"Error extracting article: {str(e)}")
        
        return articles
    
    def _extract_reuters_articles(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """ロイターから記事を抽出"""
        articles = []
        
        # ロイターのHTMLパターンに合わせた抽出ロジック
        for article_element in soup.select('article.story'):
            try:
                title_element = article_element.select_one('h3.story-title')
                link_element = article_element.select_one('a.story-title')
                summary_element = article_element.select_one('p.story-lede')
                date_element = article_element.select_one('time.article-time')
                
                if title_element and link_element:
                    title = title_element.text.strip()
                    url = link_element.get('href')
                    if not url.startswith('http'):
                        url = f"https://jp.reuters.com{url}"
                    
                    summary = ""
                    if summary_element:
                        summary = summary_element.text.strip()
                    
                    published_date = datetime.datetime.now().isoformat()
                    if date_element:
                        date_text = date_element.text.strip()
                        published_date = self._parse_japanese_date(date_text)
                    
                    articles.append({
                        "title": title,
                        "url": url,
                        "summary": summary,
                        "published_date": published_date,
                        "content": ""
                    })
            except Exception as e:
                print(f"Error extracting Reuters article: {str(e)}")
        
        return articles
    
    # 他のニュースサイト用の抽出メソッドも同様に実装
    # _extract_bloomberg_articles, _extract_cnbc_articles など
    
    def _extract_generic_articles(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """汎用的な記事抽出ロジック"""
        articles = []
        
        # 一般的なニュースサイトのパターンに合わせた抽出
        # h2, h3タグの中のaタグを探す
        for heading in soup.select('h2, h3'):
            try:
                link = heading.find('a')
                if link and link.has_attr('href') and link.text.strip():
                    url = link['href']
                    if not url.startswith('http'):
                        # 相対URLの場合はベースURLを追加
                        if url.startswith('/'):
                            url = f"https://{soup.base.get('href', '')}{url}"
                        else:
                            url = f"https://{soup.base.get('href', '')}/{url}"
                    
                    articles.append({
                        "title": link.text.strip(),
                        "url": url,
                        "summary": "",
                        "published_date": datetime.datetime.now().isoformat(),
                        "content": ""
                    })
            except Exception as e:
                print(f"Error extracting generic article: {str(e)}")
        
        return articles
    
    def _parse_japanese_date(self, date_text: str) -> str:
        """
        日本語の日付テキストをISO形式に変換
        例: "2023年5月1日" -> "2023-05-01T00:00:00"
        """
        try:
            # 年月日の抽出
            year_match = re.search(r'(\d{4})年', date_text)
            month_match = re.search(r'(\d{1,2})月', date_text)
            day_match = re.search(r'(\d{1,2})日', date_text)
            
            if year_match and month_match and day_match:
                year = int(year_match.group(1))
                month = int(month_match.group(1))
                day = int(day_match.group(1))
                
                # 時間の抽出（存在する場合）
                hour = 0
                minute = 0
                hour_match = re.search(r'(\d{1,2})時', date_text)
                minute_match = re.search(r'(\d{1,2})分', date_text)
                
                if hour_match:
                    hour = int(hour_match.group(1))
                if minute_match:
                    minute = int(minute_match.group(1))
                
                # datetime形式に変換
                date_obj = datetime.datetime(year, month, day, hour, minute)
                return date_obj.isoformat()
            
            # 「〇時間前」「〇日前」などの相対表現
            hours_ago_match = re.search(r'(\d+)時間前', date_text)
            days_ago_match = re.search(r'(\d+)日前', date_text)
            minutes_ago_match = re.search(r'(\d+)分前', date_text)
            
            now = datetime.datetime.now()
            
            if hours_ago_match:
                hours = int(hours_ago_match.group(1))
                date_obj = now - datetime.timedelta(hours=hours)
                return date_obj.isoformat()
            elif days_ago_match:
                days = int(days_ago_match.group(1))
                date_obj = now - datetime.timedelta(days=days)
                return date_obj.isoformat()
            elif minutes_ago_match:
                minutes = int(minutes_ago_match.group(1))
                date_obj = now - datetime.timedelta(minutes=minutes)
                return date_obj.isoformat()
            
            # 「今日」「昨日」などの表現
            if '今日' in date_text:
                return now.isoformat()
            elif '昨日' in date_text:
                yesterday = now - datetime.timedelta(days=1)
                return yesterday.isoformat()
        
        except Exception as e:
            print(f"Error parsing date: {date_text}, {str(e)}")
        
        # 解析できない場合は現在時刻を返す
        return datetime.datetime.now().isoformat()
    
    def _is_relevant_article(self, article: Dict[str, Any], 
                           keywords: List[str], companies: List[str]) -> bool:
        """
        記事が関連性があるか判定
        
        Args:
            article: 記事データ
            keywords: 検索キーワード
            companies: 対象企業
        
        Returns:
            関連性があればTrue
        """
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        
        # タイトルまたはサマリーに関連キーワードが含まれるか
        for keyword in keywords:
            if keyword.lower() in title or keyword.lower() in summary:
                return True
        
        # タイトルまたはサマリーに対象企業名が含まれるか
        for company in companies:
            if company.lower() in title or company.lower() in summary:
                return True
        
        return False
    
    def _fetch_article_content(self, url: str) -> str:
        """
        記事URLから本文を取得
        
        Args:
            url: 記事のURL
        
        Returns:
            記事本文
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # メタディスクリプションを取得
            description = ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.has_attr('content'):
                description = meta_desc['content']
            
            # 本文と思われる要素を抽出（記事本文は通常pタグに含まれる）
            content_elements = soup.select('article p, .article-body p, .article-content p, .story-content p')
            content = ' '.join([elem.text for elem in content_elements])
            
            # 本文が取得できなかった場合はdivタグから探す
            if not content:
                content_divs = soup.select('article, .article-body, .article-content, .story-content')
                for div in content_divs:
                    content = div.text
                    break
            
            # それでも取得できない場合はディスクリプションを返す
            if not content and description:
                return description
            
            return content
        
        except Exception as e:
            print(f"Error fetching article content from {url}: {str(e)}")
            return ""
    
    def _analyze_news_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        収集した記事を分析
        
        Args:
            articles: 収集した記事リスト
        
        Returns:
            分析結果を含む記事リスト
        """
        analyzed_articles = []
        
        for article in articles:
            try:
                # 記事タイトルと要約からの予備分析
                preliminary_analysis = self._analyze_text(article["title"] + " " + article["summary"])
                
                # 予備分析の結果、関連性スコアが低い場合はスキップ
                if preliminary_analysis["relevance_score"] < 0.3:
                    continue
                
                # 記事の本文を取得（必要な場合のみ）
                if not article["content"] and preliminary_analysis["relevance_score"] > 0.5:
                    article["content"] = self._fetch_article_content(article["url"])
                
                # 記事全体の詳細分析
                if article["content"]:
                    full_analysis = self._analyze_text(article["content"], detailed=True)
                    analysis_result = {**preliminary_analysis, **full_analysis}
                else:
                    analysis_result = preliminary_analysis
                
                # Bedrockモデルを使用した高度な分析
                market_impact = self._analyze_market_impact(article)
                
                # 分析結果を記事に追加
                analyzed_article = {**article, "analysis": analysis_result, "market_impact": market_impact}
                analyzed_articles.append(analyzed_article)
            
            except Exception as e:
                print(f"Error analyzing article {article.get('title')}: {str(e)}")
        
        return analyzed_articles
    
    def _analyze_text(self, text: str, detailed: bool = False) -> Dict[str, Any]:
        """
        テキストの感情分析と関連性評価
        
        Args:
            text: 分析対象テキスト
            detailed: 詳細分析モード
        
        Returns:
            分析結果
        """
        # テキストの長さを制限（AWS Comprehendの制限）
        text = text[:5000]
        
        try:
            # 感情分析
            sentiment_response = self.comprehend_client.detect_sentiment(
                Text=text,
                LanguageCode='ja'
            )
            
            # エンティティ抽出
            entities_response = self.comprehend_client.detect_entities(
                Text=text,
                LanguageCode='ja'
            )
            
            # キーフレーズ抽出
            key_phrases_response = self.comprehend_client.detect_key_phrases(
                Text=text,
                LanguageCode='ja'
            )
            
            # 基本分析結果
            analysis = {
                "sentiment": sentiment_response.get("Sentiment"),
                "sentiment_scores": sentiment_response.get("SentimentScore"),
                "entities": [
                    {
                        "text": entity.get("Text"),
                        "type": entity.get("Type"),
                        "score": entity.get("Score")
                    }
                    for entity in entities_response.get("Entities", [])
                ],
                "key_phrases": [
                    {
                        "text": phrase.get("Text"),
                        "score": phrase.get("Score")
                    }
                    for phrase in key_phrases_response.get("KeyPhrases", [])
                ],
                "relevance_score": self._calculate_relevance_score(
                    entities_response.get("Entities", []),
                    key_phrases_response.get("KeyPhrases", [])
                )
            }
            
            # 詳細分析モードの場合は追加情報を取得
            if detailed:
                # トピック検出（必要に応じて）
                # dominant_language = self.comprehend_client.detect_dominant_language(Text=text)
                # language_code = dominant_language['Languages'][0]['LanguageCode']
                
                # トピック分類
                try:
                    classification_response = self.comprehend_client.classify_document(
                        Text=text,
                        EndpointArn='your-classification-endpoint-arn'  # 事前に作成したエンドポイント
                    )
                    analysis["topics"] = classification_response.get("Classes", [])
                except:
                    # エンドポイントがない場合はスキップ
                    analysis["topics"] = []
            
            return analysis
        
        except Exception as e:
            print(f"Error in text analysis: {str(e)}")
            return {
                "sentiment": "NEUTRAL",
                "sentiment_scores": {"Positive": 0, "Negative": 0, "Neutral": 1, "Mixed": 0},
                "entities": [],
                "key_phrases": [],
                "relevance_score": 0.1
            }
    
    def _calculate_relevance_score(self, entities: List[Dict[str, Any]], 
                                key_phrases: List[Dict[str, Any]]) -> float:
        """
        エンティティとキーフレースから関連性スコアを計算
        
        Args:
            entities: 検出されたエンティティリスト
            key_phrases: 検出されたキーフレーズリスト
        
        Returns:
            関連性スコア (0.0〜1.0)
        """
        relevant_entity_types = ["ORGANIZATION", "COMMERCIAL_ITEM", "TITLE", "PERSON"]
        financial_terms = ["株価", "投資", "金融", "経済", "市場", "取引", "証券", "銀行", "円", "ドル", "為替", "金利"]
        
        # 関連するエンティティを数える
        relevant_entity_count = sum(1 for entity in entities 
                                  if entity.get("Type") in relevant_entity_types)
        
        # 金融関連のキーフレーズを数える
        finance_phrase_count = 0
        for phrase in key_phrases:
            phrase_text = phrase.get("Text", "").lower()
            if any(term in phrase_text for term in financial_terms):
                finance_phrase_count += 1
        
        # 総合スコアの計算
        total_entities = max(1, len(entities))
        total_phrases = max(1, len(key_phrases))
        
        entity_score = min(1.0, relevant_entity_count / total_entities)
        phrase_score = min(1.0, finance_phrase_count / total_phrases)
        
        # 重み付けした最終スコア
        return 0.6 * entity_score + 0.4 * phrase_score
    
    def _analyze_market_impact(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        記事の市場への影響を分析
        
        Args:
            article: 記事データ
        
        Returns:
            市場影響分析結果
        """
        # Bedrockモデルへのプロンプト作成
        article_text = f"タイトル: {article['title']}\n"
        if article["summary"]:
            article_text += f"要約: {article['summary']}\n"
        if article["content"]:
            # 長すぎる本文は切り詰める
            content = article["content"][:2000] + ("..." if len(article["content"]) > 2000 else "")
            article_text += f"本文: {content}\n"
        
        prompt = f"""
        以下のニュース記事を分析し、日本株市場への潜在的な影響を評価してください。
        
        {article_text}
        
        以下の項目について分析結果を提供してください:
        1. 市場影響の方向性 (ポジティブ/ネガティブ/ニュートラル)
        2. 影響の強さ (1-10のスケール)
        3. 影響が考えられるセクターまたは銘柄
        4. 影響のタイムフレーム (短期/中期/長期)
        5. 重要なポイントや注目すべき要素
        
        回答は簡潔にJSON形式で提供してください。
        """
        
        try:
            # Bedrockモデルの呼び出し
            response = self.invoke_model(prompt, {
                "temperature": 0.2,
                "max_tokens": 1024
            })
            
            # レスポンスからJSONを抽出
            response_text = response.get("text", "")
            try:
                # JSON部分の抽出を試みる
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    json_str = json_match.group(0)
                    impact_data = json.loads(json_str)
                else:
                    # 構造化されていない場合は手動でパース
                    impact_data = self._parse_unstructured_response(response_text)
            except:
                # JSON解析に失敗した場合は手動でパース
                impact_data = self._parse_unstructured_response(response_text)
            
            return impact_data
        
        except Exception as e:
            print(f"Error analyzing market impact: {str(e)}")
            return {
                "direction": "neutral",
                "strength": 0,
                "affected_sectors": [],
                "timeframe": "unknown",
                "key_points": []
            }
    
    def _parse_unstructured_response(self, text: str) -> Dict[str, Any]:
        """
        構造化されていないモデルレスポンスをパース
        
        Args:
            text: モデルの出力テキスト
        
        Returns:
            構造化されたデータ
        """
        result = {
            "direction": "neutral",
            "strength": 0,
            "affected_sectors": [],
            "timeframe": "unknown",
            "key_points": []
        }
        
        # 方向性の抽出
        if "ポジティブ" in text.lower():
            result["direction"] = "positive"
        elif "ネガティブ" in text.lower():
            result["direction"] = "negative"
        
        # 強さの抽出 (1-10の数値)
        strength_match = re.search(r'強さ.*?(\d+)', text)
        if strength_match:
            try:
                result["strength"] = int(strength_match.group(1))
            except:
                pass
        
        # セクターの抽出
        sectors = []
        sector_patterns = [
            r'セクター.*?[:：](.+?)(?:\n|$)',
            r'銘柄.*?[:：](.+?)(?:\n|$)',
            r'影響が考えられる(.+?)(?:\n|$)'
        ]
        
        for pattern in sector_patterns:
            match = re.search(pattern, text)
            if match:
                sectors_text = match.group(1)
                sectors = [s.strip() for s in re.split(r'[,、]', sectors_text) if s.strip()]
                break
        
        result["affected_sectors"] = sectors
        
        # タイムフレームの抽出
        if "短期" in text:
            result["timeframe"] = "short_term"
        elif "中期" in text:
            result["timeframe"] = "medium_term"
        elif "長期" in text:
            result["timeframe"] = "long_term"
        
        # 重要ポイントの抽出
        points = []
        points_match = re.search(r'重要なポイント.*?[:：](.+?)(?:\n\n|$)', text, re.DOTALL)
        if points_match:
            points_text = points_match.group(1)
            # 箇条書きで分割
            points = [p.strip().strip('-').strip() for p in re.split(r'\n-|\n\d+\.', points_text) if p.strip()]
        
        result["key_points"] = points
        
        return result
    
    def _categorize_news(self, analyzed_news: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析したニュースをカテゴリ別・影響別に整理
        
        Args:
            analyzed_news: 分析済みニュースリスト
        
        Returns:
            カテゴリ別・影響別のニュース
        """
        categories = {
            "economic_policy": [],  # 経済政策
            "corporate_news": [],   # 企業ニュース
            "market_trends": [],    # 市場トレンド
            "global_events": [],    # 国際情勢
            "others": []            # その他
        }
        
        impacts = {
            "positive": [],  # ポジティブな影響
            "negative": [],  # ネガティブな影響
            "neutral": []    # 中立的
        }
        
        for article in analyzed_news:
            # カテゴリ分類
            category = self._determine_category(article)
            categories[category].append(article)
            
            # 影響別分類
            impact = article.get("market_impact", {}).get("direction", "neutral")
            impacts[impact].append(article)
        
        return {
            "by_category": categories,
            "by_impact": impacts,
            "timestamp": datetime.datetime.now().isoformat()
        }
    
    def _determine_category(self, article: Dict[str, Any]) -> str:
        """
        記事のカテゴリを判定
        
        Args:
            article: 記事データ
        
        Returns:
            カテゴリ名
        """
        # エンティティと内容に基づいてカテゴリを判定
        entities = article.get("analysis", {}).get("entities", [])
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        
        # 経済政策関連キーワード
        policy_keywords = ["日銀", "金融政策", "利上げ", "利下げ", "政府", "財務省", "金融庁", "規制", "法案"]
        
        # 企業ニュース関連キーワード
        corporate_keywords = ["決算", "業績", "株主", "配当", "合併", "買収", "新製品", "開発", "特許"]
        
        # 市場トレンド関連キーワード
        market_keywords = ["相場", "株価", "指数", "トレンド", "バブル", "暴落", "急騰", "下落", "上昇"]
        
        # 国際情勢関連キーワード
        global_keywords = ["米国", "中国", "欧州", "アジア", "戦争", "紛争", "国際", "外交", "関税", "制裁"]
        
        # キーワードマッチングによるカテゴリ判定
        text = title + " " + summary
        
        if any(keyword in text for keyword in policy_keywords):
            return "economic_policy"
        
        if any(keyword in text for keyword in corporate_keywords):
            return "corporate_news"
        
        if any(keyword in text for keyword in market_keywords):
            return "market_trends"
        
        if any(keyword in text for keyword in global_keywords):
            return "global_events"
        
        # エンティティタイプに基づく判定
        organization_count = sum(1 for entity in entities if entity.get("type") == "ORGANIZATION")
        person_count = sum(1 for entity in entities if entity.get("type") == "PERSON")
        
        if organization_count > 2:
            return "corporate_news"
        
        # デフォルトはその他
        return "others"
    
    def _save_data_to_s3(self, news_data: Dict[str, Any], conversation_id: str):
        """
        収集・分析したニュースデータをS3に保存
        
        Args:
            news_data: ニュースデータ
            conversation_id: 会話ID
        """
        # 全体データをJSONとして保存
        self.s3_client.put_object(
            Body=json.dumps(news_data),
            Bucket=self.s3_bucket,
            Key=f"{self.s3_prefix}{conversation_id}/news_data_full.json",
            ContentType="application/json"
        )
        
        # カテゴリ別データを保存
        categorized = news_data.get("categorized_news", {})
        if categorized:
            self.s3_client.put_object(
                Body=json.dumps(categorized),
                Bucket=self.s3_bucket,
                Key=f"{self.s3_prefix}{conversation_id}/news_categorized.json",
                ContentType="application/json"
            )
    
    def _create_news_summary(self, news_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ニュースデータのサマリーを作成
        
        Args:
            news_data: ニュースデータ
        
        Returns:
            サマリー情報
        """
        analyzed_articles = news_data.get("analyzed_articles", [])
        categorized = news_data.get("categorized_news", {})
        
        # 影響別のカウント
        impact_counts = {
            "positive": len(categorized.get("by_impact", {}).get("positive", [])),
            "negative": len(categorized.get("by_impact", {}).get("negative", [])),
            "neutral": len(categorized.get("by_impact", {}).get("neutral", []))
        }
        
        # カテゴリ別のカウント
        category_counts = {
            category: len(items) 
            for category, items in categorized.get("by_category", {}).items()
        }
        
        # 重要ニュース（影響力が高いもの）のピックアップ
        important_news = []
        for article in analyzed_articles:
            impact = article.get("market_impact", {})
            if impact.get("strength", 0) >= 7:  # 強い影響力のニュースのみ
                important_news.append({
                    "title": article.get("title"),
                    "impact_direction": impact.get("direction", "neutral"),
                    "impact_strength": impact.get("strength", 0),
                    "affected_sectors": impact.get("affected_sectors", []),
                    "source": article.get("source"),
                    "url": article.get("url")
                })
        
        # サマリーの作成
        summary = {
            "total_articles": len(analyzed_articles),
            "impact_distribution": impact_counts,
            "category_distribution": category_counts,
            "important_news": important_news[:5],  # 上位5件のみ
            "collected_at": datetime.datetime.now().isoformat()
        }
        
        return summary