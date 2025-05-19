from typing import Any, Dict, TypedDict


class FeedConfig(TypedDict):
    base_url: str
    feed_symbol: str
    display_name: str
    feeds: Dict[str, Dict[str, Any]]


RSS_FEEDS: Dict[str, FeedConfig] = {
    "borsen": {
        "base_url": "borsen.dk",
        "feed_symbol": "BO",
        "display_name": "Børsen",
        "feeds": {
            "baeredygtig": {"path": "/rss/baeredygtig", "display_name": "Bæredygtig"},
            "ejendomme": {"path": "/rss/ejendomme", "display_name": "Ejendomme"},
            "finans": {"path": "/rss/finans", "display_name": "Finans"},
            "investor": {"path": "/rss/investor", "display_name": "Investor"},
            "ledelse": {"path": "/rss/executive", "display_name": "Ledelse"},
            "longread": {"path": "/rss/longread", "display_name": "Long Read"},
            "markedsberetninger": {
                "path": "/rss/markedsberetninger",
                "display_name": "Markedsberetninger",
            },
            "opinion": {"path": "/rss/opinion", "display_name": "Opinion"},
            "pleasure": {"path": "/rss/pleasure", "display_name": "Pleasure"},
            "politik": {"path": "/rss/politik", "display_name": "Politik"},
            "tech": {"path": "/rss/tech", "display_name": "Tech"},
            "udland": {"path": "/rss/udland", "display_name": "Udland"},
            "virksomheder": {
                "path": "/rss/virksomheder",
                "display_name": "Virksomheder",
            },
            "okonomi": {"path": "/rss/okonomi", "display_name": "Økonomi"},
        },
    },
    "bloomberg": {
        "base_url": "www.bloomberg.com",
        "feed_symbol": "BBG",
        "display_name": "Bloomberg",
        "feeds": {
            "latest": {
                "path": "/lineup-next/api/stories?limit=25&pageNumber=1&types=ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS",
                "display_name": "Latest",
            }
        },
    },
    "techcrunch": {
        "base_url": "techcrunch.com",
        "feed_symbol": "TC",
        "display_name": "TechCrunch",
        "feeds": {"latest": {"path": "/feed/", "display_name": "Latest"}},
    },
    "financial_times": {
        "base_url": "www.ft.com",
        "feed_symbol": "FT",
        "display_name": "Financial Times",
        "feeds": {
            "latest": {"path": "/news-feed?format=rss", "display_name": "Latest"}
        },
    },
    "al_jazeera_english": {
        "base_url": "www.aljazeera.com",
        "feed_symbol": "AJE",
        "display_name": "Al Jazeera English",
        "feeds": {"latest": {"path": "/xml/rss/all.xml", "display_name": "Latest"}},
    },
    "jyllands_posten": {
        "base_url": "newsletter-proxy.aws.jyllands-posten.dk",
        "feed_symbol": "JP",
        "display_name": "Jyllands-Posten",
        "feeds": {
            "latest": {
                "path": "/v1/latestNewsRss/jyllands-posten.dk?count=20",
                "display_name": "Latest",
            }
        },
    },
    "politico": {
        "base_url": "www.politico.eu",
        "feed_symbol": "PEU",
        "display_name": "Politico EU",
        "feeds": {"latest": {"path": "/feed/", "display_name": "Latest"}},
    },
    "tradingeconomics": {
        "base_url": "tradingeconomics.com",
        "feed_symbol": "TE",
        "display_name": "Trading Economics",
        "feeds": {
            "latest": {
                "path": "/ws/stream.ashx?start=0&size=20",
                "display_name": "Latest",
            }
        },
    },
    "investing.com": {
        "base_url": "www.investing.com",
        "feed_symbol": "INV",
        "display_name": "Investing.com",
        "feeds": {
            "economic_indicators": {
                "path": "/rss/news_95.rss",
                "display_name": "Economic Indicators",
            },
            "economy_news": {
                "path": "/rss/news_14.rss",
                "display_name": "Economy News",
            },
            "forex_news": {"path": "/rss/news_1.rss", "display_name": "Forex News"},
            "commodities_and_futures": {
                "path": "/rss/news_11.rss",
                "display_name": "Commodities & Futures",
            },
            "crypto": {"path": "/rss/news_301.rss", "display_name": "Cryptocurrency"},
        },
    },
    "forexlive": {
        "base_url": "www.forexlive.com",
        "feed_symbol": "FXL",
        "display_name": "Forexlive",
        "feeds": {
            "news": {"path": "/feed/news", "display_name": "News"},
            "central_bank": {
                "path": "/feed/centralbank",
                "display_name": "Central Bank",
            },
            "crypto": {
                "path": "/feed/cryptocurrency",
                "display_name": "Cryptocurrency",
            },
        },
    },
    "the_guardian": {
        "base_url": "www.theguardian.com",
        "feed_symbol": "GUA",
        "display_name": "The Guardian",
        "feeds": {"world": {"path": "/world/rss", "display_name": "World"}},
    },
    "south_china_morning_post": {
        "base_url": "www.scmp.com",
        "feed_symbol": "SCMP",
        "display_name": "South China Morning Post",
        "feeds": {
            "china": {"path": "/rss/4/feed", "display_name": "China"},
            "asia": {"path": "/rss/3/feed", "display_name": "Asia"},
            "world": {"path": "/rss/5/feed", "display_name": "World"},
            "china_policies_and_politics": {
                "path": "/rss/318198/feed",
                "display_name": "China Policies & Politics",
            },
            "china_diplomacy_and_defence": {
                "path": "/rss/318199/feed",
                "display_name": "China Diplomacy & Defence",
            },
            "china_economy": {
                "path": "/rss/318421/feed",
                "display_name": "China Economy",
            },
            "usa_and_canada": {
                "path": "/rss/322262/feed",
                "display_name": "USA & Canada",
            },
            "europe": {"path": "/rss/322263/feed", "display_name": "Europe"},
            "east_asia": {"path": "/rss/318214/feed", "display_name": "East Asia"},
            "southeast_asia": {
                "path": "/rss/318215/feed",
                "display_name": "Southeast Asia",
            },
            "south_asia": {"path": "/rss/318216/feed", "display_name": "South Asia"},
            "asia_diplomacy": {
                "path": "/rss/318213/feed",
                "display_name": "Asia Diplomacy",
            },
            "business": {"path": "/rss/92/feed", "display_name": "Business"},
            "companies": {"path": "/rss/10/feed", "display_name": "Companies"},
            "global_economy": {
                "path": "/rss/12/feed",
                "display_name": "Global Economy",
            },
        },
    },
    "deutsche_welle": {
        "base_url": "rss.dw.com",
        "feed_symbol": "DW",
        "display_name": "Deutsche Welle",
        "feeds": {
            "world": {"path": "/rdf/rss-en-world", "display_name": "World"},
            "europe": {"path": "/rdf/rss-en-eu", "display_name": "Europe"},
            "germany": {"path": "/rdf/rss-en-ger", "display_name": "Germany"},
            "business": {"path": "/rdf/rss-en-bus", "display_name": "Business"},
        },
    },
    "abc_news_australia": {
        "base_url": "www.abc.net.au",
        "feed_symbol": "ABC",
        "display_name": "ABC News Australia",
        "feeds": {
            "business": {
                "path": "/news/feed/104217374/rss.xml",
                "display_name": "Business",
            }
        },
    },
    "financial_post": {
        "base_url": "financialpost.com",
        "feed_symbol": "FP",
        "display_name": "Financial Post",
        "feeds": {
            "economy": {
                "path": "/category/news/economy/feed.xml",
                "display_name": "Economy",
            }
        },
    },
    "coindesk": {
        "base_url": "www.coindesk.com",
        "feed_symbol": "COIN",
        "display_name": "CoinDesk",
        "feeds": {
            "latest": {"path": "/arc/outboundfeeds/rss", "display_name": "Latest"}
        },
    },
}
JSON_FIELD_MAPPINGS = {
    "bloomberg": {
        "title": "headline",
        "published_date": "publishedAt",
        "url": "url",
        "description": "summary",
        "author_name": "byline",
    },
    "tradingeconomics": {
        "title": "title",
        "published_date": "date",
        "url": "url",
        "description": "description",
        "author_name": "author",
    },
}

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15"
DEFAULT_HEADERS = {"Accept": "*/*", "Accept-Encoding": "gzip"}
