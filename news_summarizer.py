#!/usr/bin/env python3
"""
Daily News Summarizer
Fetches articles from Feedbin, summarizes with ChatGPT, and emails results
"""

import os
import requests
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
import json
import time

class NewsSymmarizer:
    def __init__(self):
        # API credentials - reading from environment variables for GitHub Actions
        # For local testing, you can set these directly or use environment variables
        self.feedbin_email = os.getenv('FEEDBIN_EMAIL', 'YOUR_FEEDBIN_EMAIL_HERE')
        self.feedbin_password = os.getenv('FEEDBIN_PASSWORD', 'YOUR_FEEDBIN_PASSWORD_HERE')
        self.openai_api_key = os.getenv('OPENAI_API_KEY', 'YOUR_OPENAI_API_KEY_HERE')
        
        # Email settings
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.email_user = os.getenv('EMAIL_USER', 'YOUR_EMAIL_HERE')
        self.email_password = os.getenv('EMAIL_PASSWORD', 'YOUR_EMAIL_APP_PASSWORD_HERE')
        self.recipient_email = os.getenv('RECIPIENT_EMAIL', 'WHERE_TO_SEND_SUMMARY@example.com')
        
        # API endpoints
        self.feedbin_base_url = 'https://api.feedbin.com/v2'
        self.openai_base_url = 'https://api.openai.com/v1'
        
        # Token usage tracking
        self.tokens_used_today = 0
        self.estimated_cost_today = 0.0
    
    def fetch_recent_articles(self, hours_back: int = 24) -> List[Dict]:
        """Fetch articles from the last N hours from Feedbin"""
        
        print(f"🔍 DEBUG: Fetching articles from last {hours_back} hours")
        print(f"🔍 DEBUG: Using Feedbin email: {self.feedbin_email}")
        
        # Calculate timestamp for N hours ago
        since_time = datetime.now() - timedelta(hours=hours_back)
        since_param = since_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"🔍 DEBUG: Looking for articles since: {since_param}")
        
        # First, let's check if we can connect to Feedbin at all
        print("🔍 DEBUG: Testing Feedbin authentication...")
        auth_test_url = f"{self.feedbin_base_url}/subscriptions.json"
        auth_response = requests.get(auth_test_url, auth=(self.feedbin_email, self.feedbin_password))
        
        if auth_response.status_code != 200:
            print(f"❌ ERROR: Feedbin authentication failed: {auth_response.status_code}")
            print(f"Response: {auth_response.text}")
            return []
        else:
            subscriptions = auth_response.json()
            print(f"✅ SUCCESS: Connected to Feedbin. You have {len(subscriptions)} subscriptions")
            if subscriptions:
                print("📰 Your feeds:")
                for sub in subscriptions[:5]:  # Show first 5 feeds
                    print(f"  - {sub.get('title', 'Unknown')} ({sub.get('site_url', 'No URL')})")
                if len(subscriptions) > 5:
                    print(f"  ... and {len(subscriptions) - 5} more feeds")
        
        # Get entries from Feedbin - try without date filter first
        print("🔍 DEBUG: Fetching recent entries...")
        entries_url = f"{self.feedbin_base_url}/entries.json"
        
        # Try getting entries without date filter first to see if there are any
        print("🔍 DEBUG: First, checking if there are ANY recent entries...")
        no_filter_response = requests.get(
            entries_url,
            auth=(self.feedbin_email, self.feedbin_password),
            params={'per_page': 10}  # Just get 10 most recent
        )
        
        if no_filter_response.status_code == 200:
            recent_entries = no_filter_response.json()
            print(f"✅ Found {len(recent_entries)} recent entries (without date filter)")
            if recent_entries:
                latest_entry = recent_entries[0]
                print(f"📅 Latest entry published: {latest_entry.get('published', 'No date')}")
                print(f"📰 Latest entry title: {latest_entry.get('title', 'No title')}")
        else:
            print(f"❌ ERROR: Could not fetch entries: {no_filter_response.status_code}")
            return []
        
        # Now try with date filter
        params = {'since': since_param, 'per_page': 50}
        print(f"🔍 DEBUG: Now trying with date filter: since={since_param}")
        
        response = requests.get(
            entries_url,
            auth=(self.feedbin_email, self.feedbin_password),
            params=params
        )
        
        if response.status_code != 200:
            print(f"❌ ERROR: Failed to fetch filtered articles: {response.status_code}")
            print(f"Response: {response.text}")
            return []
        
        articles = response.json()
        print(f"✅ Found {len(articles)} articles with date filter")
        
        if not articles:
            print("⚠️  No articles found with current date filter. Trying without date filter...")
            # If no articles with date filter, get some recent ones anyway for testing
            fallback_response = requests.get(
                entries_url,
                auth=(self.feedbin_email, self.feedbin_password),
                params={'per_page': 20}
            )
            if fallback_response.status_code == 200:
                articles = fallback_response.json()
                print(f"📰 Using {len(articles)} recent articles for testing (ignoring date filter)")
        
        # Filter and format articles
        formatted_articles = []
        for article in articles:
            formatted_articles.append({
                'title': article.get('title', 'No Title'),
                'url': article.get('url', ''),
                'summary': article.get('summary', ''),
                'content': article.get('content', ''),
                'published': article.get('published', ''),
                'feed_name': self.get_feed_name(article.get('feed_id'))
            })
        
        print(f"🔍 DEBUG: Returning {len(formatted_articles)} formatted articles")
        return formatted_articles
    
    def get_feed_name(self, feed_id: int) -> str:
        """Get feed name from feed ID"""
        if not feed_id:
            return "Unknown Feed"
            
        feed_url = f"{self.feedbin_base_url}/subscriptions.json"
        response = requests.get(
            feed_url,
            auth=(self.feedbin_email, self.feedbin_password)
        )
        
        if response.status_code == 200:
            feeds = response.json()
            for feed in feeds:
                if feed.get('feed_id') == feed_id:
                    return feed.get('title', 'Unknown Feed')
        
        return "Unknown Feed"
    
    def clean_text(self, text: str) -> str:
        """Clean HTML and excessive whitespace from text"""
        import re
        from html import unescape
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        text = unescape(text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def get_api_usage_info(self) -> Dict:
        """Get current API usage and billing information from OpenAI"""
        
        headers = {
            'Authorization': f'Bearer {self.openai_api_key}',
            'Content-Type': 'application/json'
        }
        
        # Get usage information (this endpoint shows usage data)
        usage_info = {
            'current_usage': None,
            'billing_info': None,
            'error': None
        }
        
        try:
            # Get usage data for current billing period
            # Note: OpenAI's usage endpoint format may change
            today = datetime.now().strftime('%Y-%m-%d')
            start_of_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            
            usage_url = f"{self.openai_base_url}/usage"
            params = {
                'start_date': start_of_month,
                'end_date': today
            }
            
            response = requests.get(usage_url, headers=headers, params=params)
            
            if response.status_code == 200:
                usage_data = response.json()
                usage_info['current_usage'] = usage_data
            else:
                usage_info['error'] = f"Usage API error: {response.status_code}"
                
        except Exception as e:
            usage_info['error'] = f"Error fetching usage: {str(e)}"
        
        return usage_info
    
    def estimate_token_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on token usage"""
        
        # Current OpenAI pricing (as of late 2024/early 2025)
        pricing = {
            'gpt-4': {'input': 0.03, 'output': 0.06},  # per 1K tokens
            'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},  # per 1K tokens
            'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
        }
        
        if model not in pricing:
            # Default to GPT-4 pricing if unknown model
            model = 'gpt-4'
            
        input_cost = (input_tokens / 1000) * pricing[model]['input']
        output_cost = (output_tokens / 1000) * pricing[model]['output']
        
        return input_cost + output_cost
    
    def display_usage_summary(self):
        """Display current API usage and cost information"""
        
        print("\n" + "="*50)
        print("📊 CHATGPT API USAGE SUMMARY")
        print("="*50)
        
        # Show today's session usage
        if self.tokens_used_today > 0:
            print(f"Today's session:")
            print(f"  Tokens used: {self.tokens_used_today:,}")
            print(f"  Estimated cost: ${self.estimated_cost_today:.4f}")
        
        # Try to get overall account usage
        usage_info = self.get_api_usage_info()
        
        if usage_info['error']:
            print(f"\n⚠️  Could not fetch account usage: {usage_info['error']}")
            print("This is normal - OpenAI's usage API has limited access.")
        else:
            current_usage = usage_info.get('current_usage')
            if current_usage:
                total_usage = current_usage.get('total_usage', 0) / 100  # Convert from cents
                print(f"\n📈 Account Usage This Month:")
                print(f"  Total spent: ${total_usage:.2f}")
        
        # Display helpful context
        print(f"\n💡 Cost Context:")
        print(f"  GPT-3.5-turbo: ~$0.002 per 1K tokens")
        print(f"  GPT-4: ~$0.045 per 1K tokens")
        print(f"  Average daily run: 2K-5K tokens")
        
        # Show recommendations
        if self.estimated_cost_today > 0.10:  # More than 10 cents
            print(f"\n💰 Cost Tip: Consider switching to GPT-3.5-turbo to reduce costs")
        
        print("="*50 + "\n")
    
    def summarize_with_chatgpt(self, articles: List[Dict]) -> str:
        """Send articles to ChatGPT for summarization"""
        
        if not articles:
            return "No new articles found in the specified time period."
        
        # Prepare articles text for ChatGPT
        articles_text = ""
        for i, article in enumerate(articles[:20], 1):  # Limit to 20 articles to avoid token limits
            clean_summary = self.clean_text(article['summary'] or article['content'])
            # Truncate very long articles
            if len(clean_summary) > 500:
                clean_summary = clean_summary[:500] + "..."
                
            articles_text += f"""
Article {i}:
Title: {article['title']}
Source: {article['feed_name']}
Summary: {clean_summary}
URL: {article['url']}

"""
        
        # ChatGPT prompt
        prompt = f"""Please create a concise daily news summary from the following articles. 

Format the summary as follows:
1. Start with a brief overview paragraph
2. Group similar stories together
3. For each story/topic, provide:
   - A clear headline
   - A 2-3 sentence summary
   - Key sources mentioned
4. End with any notable trends or patterns

Here are today's articles:
{articles_text}

Please focus on the most important and interesting stories, and make the summary engaging and easy to read."""

        # Make API request to ChatGPT
        headers = {
            'Authorization': f'Bearer {self.openai_api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': 'gpt-4',  # or 'gpt-3.5-turbo' for lower cost
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 1500,
            'temperature': 0.7
        }
        
        response = requests.post(
            f"{self.openai_base_url}/chat/completions",
            headers=headers,
            json=data
        )
        
        if response.status_code != 200:
            print(f"Error with ChatGPT API: {response.status_code}")
            return f"Error generating summary. Found {len(articles)} articles."
        
        result = response.json()
        
        # Track token usage and cost
        usage = result.get('usage', {})
        input_tokens = usage.get('prompt_tokens', 0)
        output_tokens = usage.get('completion_tokens', 0)
        total_tokens = usage.get('total_tokens', 0)
        
        # Update session tracking
        self.tokens_used_today += total_tokens
        session_cost = self.estimate_token_cost(data['model'], input_tokens, output_tokens)
        self.estimated_cost_today += session_cost
        
        # Display token usage info
        print(f"🔤 Tokens used: {total_tokens:,} (input: {input_tokens:,}, output: {output_tokens:,})")
        print(f"💰 Estimated cost: ${session_cost:.4f}")
        
        return result['choices'][0]['message']['content']
    
    def send_email(self, summary: str, article_count: int):
        """Send the summary via email"""
        
        # Create email
        msg = MIMEMultipart()
        msg['From'] = self.email_user
        msg['To'] = self.recipient_email
        msg['Subject'] = f"Daily News Summary - {datetime.now().strftime('%B %d, %Y')} ({article_count} articles)"
        
        # Email body
        body = f"""
Good morning!

Here's your daily news summary based on {article_count} articles from your Feedbin subscriptions:

{summary}

---
This summary was automatically generated from your Feedbin feeds.
Generated on {datetime.now().strftime('%Y-%m-%d at %I:%M %p')}
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_user, self.email_password)
            server.send_message(msg)
            server.quit()
            print("Summary email sent successfully!")
        except Exception as e:
            print(f"Error sending email: {e}")
    
    def run_daily_summary(self, hours_back: int = 24):
        """Main function to run the daily summary"""
        print(f"Fetching articles from the last {hours_back} hours...")
        
        # Fetch articles
        articles = self.fetch_recent_articles(hours_back)
        print(f"Found {len(articles)} articles")
        
        if not articles:
            print("No articles found. Sending notification email.")
            self.send_email("No new articles found in your feeds today.", 0, [])
            return
        
        # Generate summary
        print("Generating summary with ChatGPT...")
        summary = self.summarize_with_chatgpt(articles)
        
        # Send email
        print("Sending summary email...")
        self.send_email(summary, len(articles))
        
        # Display usage summary
        self.display_usage_summary()
        
        print("Daily summary complete!")

def main():
    """Main function"""
    # Check if all required environment variables are set
    required_vars = [
        'FEEDBIN_EMAIL', 'FEEDBIN_PASSWORD', 'OPENAI_API_KEY',
        'EMAIL_USER', 'EMAIL_PASSWORD', 'RECIPIENT_EMAIL'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print("Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nFor local testing, you can set these directly in the code.")
        print("For GitHub Actions, add them as repository secrets.")
        return
    
    summarizer = NewsSymmarizer()
    
    # Run the daily summary - change hours_back for testing
    summarizer.run_daily_summary(hours_back=168)  # 168 hours = 7 days

if __name__ == "__main__":
    main()
