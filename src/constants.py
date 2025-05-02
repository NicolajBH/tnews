from typing import Dict, Optional, TypedDict


class FeedConfig(TypedDict):
    base_url: str
    feed_symbol: str
    feeds: Dict[str, str]


RSS_FEEDS: Dict[str, FeedConfig] = {
    "borsen": {
        "base_url": "borsen.dk",
        "feed_symbol": "BO",
        "feeds": {
            "baeredygtig": "/rss/baeredygtig",
            "ejendomme": "/rss/ejendomme",
            "finans": "/rss/finans",
            "investor": "/rss/investor",
            "ledelse": "/rss/executive",
            "longread": "/rss/longread",
            "markedsberetninger": "/rss/markedsberetninger",
            "opinion": "/rss/opinion",
            "pleasure": "/rss/pleasure",
            "politik": "/rss/politik",
            "tech": "/rss/tech",
            "udland": "/rss/udland",
            "virksomheder": "/rss/virksomheder",
            "okonomi": "/rss/okonomi",
        },
    },
    "bloomberg": {
        "base_url": "www.bloomberg.com",
        "feed_symbol": "BBG",
        "feeds": {
            "latest": "/lineup-next/api/stories?limit=25&pageNumber=1&types=ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS"
        },
    },
    "techcrunch": {
        "base_url": "techcrunch.com",
        "feed_symbol": "TC",
        "feeds": {"latest": "/feed/"},
    },
    "financial_times": {
        "base_url": "www.ft.com",
        "feed_symbol": "FT",
        "feeds": {"latest": "/news-feed?format=rss"},
    },
    "al_jazeera_english": {
        "base_url": "www.aljazeera.com",
        "feed_symbol": "AJE",
        "feeds": {"latest": "/xml/rss/all.xml"},
    },
    "jyllands_posten": {
        "base_url": "newsletter-proxy.aws.jyllands-posten.dk",
        "feed_symbol": "JP",
        "feeds": {"latest": "/v1/latestNewsRss/jyllands-posten.dk?count=20"},
    },
    "politico": {
        "base_url": "www.politico.eu",
        "feed_symbol": "PEU",
        "feeds": {"latest": "/feed/"},
    },
    "tradingeconomics": {
        "base_url": "tradingeconomics.com",
        "feed_symbol": "TE",
        "feeds": {"latest": "/ws/stream.ashx?start=0&size=20"},
    },
    "investing.com": {
        "base_url": "www.investing.com",
        "feed_symbol": "INV",
        "feeds": {
            "economic_indicators": "/rss/news_95.rss",
            "economy_news": "/rss/news_14.rss",
            "forex_news": "/rss/news_1.rss",
            "commodities_and_futures": "/rss/news_11.rss",
            "crypto": "/rss/news_301.rss",
        },
    },
    "forexlive": {
        "base_url": "www.forexlive.com",
        "feed_symbol": "FXL",
        "feeds": {
            "news": "/feed/news",
            "central_bank": "/feed/centralbank",
            "crypto": "/feed/cryptocurrency",
        },
    },
    "the_guardian": {
        "base_url": "www.theguardian.com",
        "feed_symbol": "GUA",
        "feeds": {"world": "/world/rss"},
    },
    "south_china_morning_post": {
        "base_url": "www.scmp.com",
        "feed_symbol": "SCMP",
        "feeds": {
            "china": "/rss/4/feed",
            "asia": "/rss/3/feed",
            "world": "/rss/5/feed",
            "china_policies_and_politics": "/rss/318198/feed",
            "china_diplomacy_and_defence": "/rss/318199/feed",
            "china_economy": "/rss/318421/feed",
            "usa_and_canada": "/rss/322262/feed",
            "europe": "/rss/322263/feed",
            "east_asia": "/rss/318214/feed",
            "southeast_asia": "/rss/318215/feed",
            "south_asia": "/rss/318216/feed",
            "asia_diplomacy": "/rss/318213/feed",
            "business": "/rss/92/feed",
            "companies": "/rss/10/feed",
            "global_economy": "/rss/12/feed",
        },
    },
    "deutsche_welle": {
        "base_url": "rss.dw.com",
        "feed_symbol": "DW",
        "feeds": {
            "world": "/rdf/rss-en-world",
            "europe": "/rdf/rss-en-eu",
            "germany": "/rdf/rss-en-ger",
            "business": "/rdf/rss-en-bus",
        },
    },
    "abc_news_australia": {
        "base_url": "www.abc.net.au",
        "feed_symbol": "ABC",
        "feeds": {"business": "/news/feed/104217374/rss.xml"},
    },
    "financial_post": {
        "base_url": "financialpost.com",
        "feed_symbol": "FP",
        "feeds": {"economy": "/category/news/economy/feed.xml"},
    },
    "coindesk": {
        "base_url": "www.coindesk.com",
        "feed_symbol": "COIN",
        "feeds": {"latest": "/arc/outboundfeeds/rss"},
    },
}

JSON_FIELD_MAPPINGS = {
    "bloomberg": {"title": "headline", "published_date": "publishedAt", "url": "url"},
    "tradingeconomics": {"title": "title", "published_date": "date", "url": "url"},
}

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15"
DEFAULT_HEADERS = {"Accept": "*/*", "Accept-Encoding": "gzip"}
