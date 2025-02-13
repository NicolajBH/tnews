from typing import List
from datetime import datetime
from src.models.article import Article, ArticleContent


def format_articles(articles: List[ArticleContent]) -> List[Article]:
    articles_by_pub_date = sorted(
        articles,
        key=lambda x: datetime.strptime(x.pubDate, "%a, %d %b %Y %H:%M:%S %z"),
        reverse=True,
    )

    seen = set()
    unique_articles = []
    for article in articles_by_pub_date:
        if article.title not in seen:
            seen.add(article.title)
            unique_articles.append(article)
    return [
        Article(
            title=article.title,
            pubDate=article.pubDate,
            source=article.source,
            formatted_time=article.formatted_date,
        )
        for article in unique_articles[:20]
    ]
