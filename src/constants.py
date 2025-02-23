from typing import Dict, TypedDict


class FeedConfig(TypedDict):
    base_url: str
    feed_symbol: str
    feeds: Dict[str, str]


RSS_FEEDS: Dict[str, FeedConfig] = {
    "borsen": {
        "base_url": "borsen.dk",
        "feed_symbol": "BORSEN",
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
}

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15"
DEFAULT_HEADERS = {"Accept": "*/*", "Accept-Encoding": "gzip"}
