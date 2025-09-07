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
from typing import List, Dict
import json
import time

class NewsSymmarizer:
    def __init__(self):
    # API credentials - now reading from environment variables
    self.feedbin_email = os.getenv('FEEDBIN_EMAIL')
    self.feedbin_password = os.getenv('FEEDBIN_PASSWORD') 
    self.openai_api_key = os.getenv('OPENAI_API_KEY')
    
    # Email settings
    self.smtp_server = "smtp.gmail.com"  # Change if not using Gmail
    self.smtp_port = 587
    self.email_user = os.getenv('EMAIL_USER')
    self.email_password = os.getenv('EMAIL_PASSWORD')
    self.recipient_email = os.getenv('RECIPIENT_EMAIL')
        
    def fetch_recent_articles(self, hours_back: int = 24) -> List[Dict]:
        """Fetch articles from the last N hours from Feedbin"""
        
        # Calculate timestamp for N hours ago
        since_time = datetime.now() - timedelta(hours=hours_back)
        since_param = since_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Get entries from Feedbin
        entries_url = f"{self.feedbin_base_url}/entries.json"
        params = {'since': since_param, 'per_page': 50}  # Adjust per_page as needed
        
        response = requests.get(
            entries_url,
            auth=(self.feedbin_email, self.feedbin_password),
            params=params
        )
        
        if response.status_code != 200:
            print(f"Error fetching articles: {response.status_code}")
            return []
        
        articles = response.json()
        
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
            self.send_email("No new articles found in your feeds today.", 0)
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
        return
    
    summarizer = NewsSymmarizer()
    
    # Run the daily summary
    summarizer.run_daily_summary()

if __name__ == "__main__":
    main()
