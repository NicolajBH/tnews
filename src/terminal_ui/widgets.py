import os
import httpx

from typing import Dict
from datetime import datetime
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Input, Label, Static
from textual.containers import Horizontal, Vertical


class TimeDisplay(Static):
    """Widget to display current time and date"""

    def on_mount(self) -> None:
        """Event handler called when the widget is added to the app"""
        self.update_time()
        self.set_interval(1, self.update_time)

    def update_time(self) -> None:
        """Update displayed time"""
        now = datetime.now()
        separator = ":" if now.second % 2 == 0 else " "
        current_time = now.strftime(f"%H{separator}%M{separator}%S")
        current_date = now.strftime("%a %d %b")
        self.update(f"{current_date} {current_time}")


class MarketIndex(Static):
    """Widget to display a market index"""

    def __init__(self, index_name: str, value: float, change: float, **kwargs):
        """initialize the market index widget"""
        self.index_name = index_name
        self.value = value
        self.change = change

        if change > 0.001:
            # Up triangle for positive change
            direction = "▲"
            change_color = "green"
            change_sign = "+"
        elif change < -0.001:
            # Down triangle for negative change
            direction = "▼"
            change_color = "red"
            change_sign = "-"
        else:
            # No triangle for no change
            direction = "–"
            change_color = "white"
            change_sign = ""

        content = f"{index_name}: {value:.2f} [{change_color}]{direction} {change_sign}{abs(change):.2f}%[/]"
        super().__init__(content, **kwargs)


class MarketsContainer(Static):
    """A container for financial market data"""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.markets = {
            "S&P 500": {
                "prevClose": 0.0,
                "currentPrice": 0.0,
                "change": 0.0,
                "ticker": "^GSPC",
            },
            "OMXC25": {
                "prevClose": 0.0,
                "currentPrice": 0.0,
                "change": 0.0,
                "ticker": "^OMXC25",
            },
            "NASDAQ-100": {
                "prevClose": 0.0,
                "currentPrice": 0.0,
                "change": 0.0,
                "ticker": "^NDX",
            },
            "BTC-USD": {
                "prevClose": 0.0,
                "currentPrice": 0.0,
                "change": 0.0,
                "ticker": "BTC-USD",
            },
        }
        # Initialize market_line as None to keep track of it
        self.market_line = None

    async def on_mount(self):
        """Initial setup when the widget is mounted."""
        if self.market_line is None:
            market_widgets = []

            for name, data in self.markets.items():
                # Create a widget for this market
                market_widgets.append(
                    MarketIndex(name, data["currentPrice"], data["change"])
                )

            # Create market line
            self.market_line = Horizontal(*market_widgets, id="market-indices")
            self.mount(self.market_line)
        await self.refresh_markets()
        # Update market data every 60 sec
        self.set_interval(60, self.refresh_markets)

    async def refresh_markets(self):
        """Update the market data with simulated changes."""
        if self.market_line is None:
            return

        market_indices = self.market_line.children

        for i, (name, data) in enumerate(self.markets.items()):
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://finance.yahoo.com/",
                }
                response = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{data['ticker']}",
                    headers=headers,
                )
                if response.status_code != 200:
                    self.app.notify(
                        f"Error trying to fetch market data. Response code: {response.status_code}"
                    )
                    return
                response_data = response.json()["chart"]["result"][0]["meta"]
                data["currentPrice"] = response_data["regularMarketPrice"]
                data["prevClose"] = response_data["previousClose"]
                change = (
                    response_data["regularMarketPrice"] / response_data["previousClose"]
                    - 1
                ) * 100
                data["change"] = change
            # Get the existing widget and update it
            if i < len(market_indices):
                # Create updated text with direction indicator
                if change > 0:
                    direction = "▲"
                    change_color = "green"
                    change_sign = "+"
                elif change < 0:
                    direction = "▼"
                    change_color = "red"
                    change_sign = "-"
                else:
                    direction = "–"
                    change_color = "white"
                    change_sign = ""

                content = f"{name}: {data['currentPrice']:.2f} [{change_color}]{direction} {change_sign}{abs(change):.2f}%[/]"

                market_indices[i].update(content)


class ArticleWidget(Static):
    """Widget to display an article"""

    def __init__(
        self,
        index: int,
        article: dict,
        terminal_width: int,
        selected_index: int = 0,
        **kwargs,
    ):
        self.index = index
        self.title = article["title"]
        self.feed_symbol = article["feed_symbol"]
        self.feed_time = article["feed_time"]
        self.article_id = article.get("id", "")
        self.article_data = article
        self.is_selected = False
        self.terminal_width = terminal_width or os.get_terminal_size().columns
        self.selected_index = selected_index

        formatted_content = self.format_articles()

        super().__init__(formatted_content, **kwargs)

    def format_articles(self) -> str:
        """Format the articles"""
        index_width = 3
        source_width = 4
        time_width = 6
        spacing = 2
        title_width = (
            self.terminal_width
            - index_width
            - source_width
            - time_width
            - (spacing * 2)
        )

        title = self.title
        if (len(title)) + 2 > title_width:
            title = title[: title_width - 6] + "..."

        if self.index == self.selected_index:
            # Current line - show actual line number (1-based)
            index_display = f"{self.index + 1}"
        else:
            # Other lines - show distance from current line
            relative_index = abs(self.index - self.selected_index)
            index_display = f"{relative_index}"

        if self.is_selected:
            content = f"[yellow on blue]{index_display:>3}  {title:<{title_width}} {self.feed_symbol:4s} {self.feed_time}[/]"
        else:
            content = f" {index_display:>3} {title:<{title_width}} {self.feed_symbol:4s} {self.feed_time}"

        return content

    def set_selected(self, selected: bool) -> None:
        """Set the selection state of this article"""
        if self.is_selected != selected:
            self.is_selected = selected
            self.update(self.format_articles())


class ArticlesContainer(Static):
    """Container for articles"""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.articles = []
        self.articles_list = None
        self.last_etag = None
        self.next_cursor = None
        self.cursor_history = []
        self.selected_index = 0
        self.params = {}
        self.terminal_width = reactive(80)
        self.terminal_height = reactive(24)
        self.latest_timestamp = None

    def on_mount(self) -> None:
        """Event handler called when the widget is added to the app"""
        self.articles_list = Vertical(id="articles-list")
        self.mount(self.articles_list)
        self.set_interval(60, self.check_for_updates)

    def update_articles(self):
        if self.articles_list is not None:
            self.articles_list.remove_children()

        self.article_widgets = []
        for i, article in enumerate(self.articles):
            widget = ArticleWidget(i, article, self.terminal_width, self.selected_index)
            self.article_widgets.append(widget)
            self.articles_list.mount(widget)

        self.refresh()
        # Select the first article after refresh
        if self.article_widgets:
            self.call_after_refresh(self.select_article, 0)

    def select_article(self, index: int) -> None:
        """Select the article at the given index"""
        # Ensure index is within bounds
        if not self.article_widgets:
            return

        index = max(0, min(index, len(self.article_widgets) - 1))

        # Deselect current selection
        if 0 <= self.selected_index < len(self.article_widgets):
            self.article_widgets[self.selected_index].set_selected(False)

        # Select new article
        old_selected_index = self.selected_index
        self.selected_index = index
        self.article_widgets[self.selected_index].set_selected(True)

        if old_selected_index != self.selected_index:
            self.update_relative_indices()

        # Ensure the selected article is visible
        try:
            self.article_widgets[self.selected_index].scroll_visible()
        except Exception as e:
            self.app.log(f"Error scrolling: {e}")

    def update_relative_indices(self):
        for widget in self.article_widgets:
            widget.selected_index = self.selected_index
            widget.update(widget.format_articles())

    def select_next_article(self) -> None:
        """Select the next article"""
        if self.article_widgets and self.selected_index < len(self.article_widgets) - 1:
            self.select_article(self.selected_index + 1)

    def select_previous_article(self) -> None:
        """Select the previous article"""
        if self.article_widgets and self.selected_index > 0:
            self.select_article(self.selected_index - 1)

    def get_selected_article(self) -> dict | None:
        """Get the currently selected article data"""
        if self.article_widgets and 0 <= self.selected_index < len(
            self.article_widgets
        ):
            return self.article_widgets[self.selected_index].article_data
        return None

    async def fetch_articles(self):
        try:
            auth_headers = self.app.auth_manager.get_auth_header()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "http://127.0.0.1:8000/api/v1/articles/latest",
                    headers=auth_headers,
                    params=self.params,
                )

                if response.status_code == 401 or response.status_code == 403:
                    if await self.app.auth_manager.refresh_access_token():
                        auth_headers = self.app.auth_manager.get_auth_header()
                        response = await client.get(
                            "http://127.0.0.1:8000/api/v1/articles/latest",
                            headers=auth_headers,
                            params=self.params,
                        )
                    else:
                        self.app.notify(
                            "Authentication error. Please login again", severity="error"
                        )
                        return False

                if "etag" in response.headers and "cursor" not in self.params:
                    self.last_etag = response.headers["etag"]
                data = response.json()

                self.articles = data["items"]

                if "cursor" not in self.params and self.articles:
                    self.latest_timestamp = self.articles[0]["formatted_pubDate"]

                if "pagination" in data and "next_cursor" in data["pagination"]:
                    self.next_cursor = data["pagination"]["next_cursor"]

                self.update_articles()
                return True
        except Exception as e:
            self.app.log(f"Error fetching articles: {e}")
            return False

    async def check_for_updates(self):
        """Check if new articles are available"""
        if not self.last_etag:
            await self.fetch_articles()
            return

        try:
            headers = self.app.auth_manager.get_auth_header()
            headers["If-None-Match"] = self.last_etag

            params = self.params.copy()
            params.pop("cursor", None)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "http://127.0.0.1:8000/api/v1/articles/latest",
                    headers=headers,
                    params=params,
                )
                if response.status_code == 304:
                    self.app.log("No new articles available")
                    return

                data = response.json()
                new_articles = 0
                for item in data["items"]:
                    if item["formatted_pubDate"] > self.latest_timestamp:
                        new_articles += 1

                if new_articles:
                    try:
                        channel_header = self.app.query_one(
                            "#channel-header", ChannelHeader
                        )
                        channel_header.set_new_articles(new_articles)
                    except Exception as e:
                        self.app.log(f"Failed to update channel header: {str(e)}")
        except Exception as e:
            self.app.log(f"Error checking for updates: {str(e)}")


class ChannelHeader(Static):
    """Header component showing current channel name"""

    def __init__(self, channel_name: str, **kwargs):
        super().__init__(**kwargs)
        self.channel_name = channel_name
        self.last_refresh = datetime.now()
        self.new_articles = 0
        self.box_widget = None

    def on_mount(self) -> None:
        """Create header"""
        container = Horizontal(
            Static(self._get_box_art(), id="channel-box"),
            Static(self._get_info_text(), id="refresh-info"),
        )
        self.mount(container)

    def _get_box_art(self) -> str:
        box_width = len(self.channel_name) + 10
        top_line = f"╔{'═' * box_width}╗"
        middle_line = f"║     {self.channel_name.upper()}     ║"
        bottom_line = f"╚{'═' * box_width}╝"
        return f"{top_line}\n{middle_line}\n{bottom_line}"

    def _get_info_text(self) -> str:
        refresh_text = f"Last updated: {self.last_refresh.strftime('%H:%M:%S')}"
        if self.new_articles > 0:
            new_text = f"[bold red]► {self.new_articles} NEW ◄[/]"
        else:
            new_text = ""

        return f"{refresh_text}\n{new_text}"

    def update_refresh_time(self, refresh_time: datetime | None = None):
        if refresh_time is None:
            refresh_time = datetime.now()
        self.last_refresh = refresh_time

        info_widget = self.app.query_one("#refresh-info", Static)
        info_widget.update(self._get_info_text())

    def set_new_articles(self, count: int):
        self.new_articles = count
        info_widget = self.app.query_one("#refresh-info", Static)
        info_widget.update(self._get_info_text())

    def update_channel(self, channel_name: str):
        self.channel_name = channel_name
        self.new_articles = 0
        if self.box_widget:
            self.box_widget.update(self._get_box_art())

        info_widget = self.app.query_one("#refresh-info", Static)
        info_widget.update(self._get_info_text())


class SourceWidget(Static):
    """Widget for displaying sources in modals"""

    def __init__(self, index: int, source_data: Dict, **kwargs):
        self.source_name = source_data["source_name"]
        self.display_name = source_data["display_name"]
        self.is_selected = False

        formatted_title = self.format_title()

        super().__init__(formatted_title, **kwargs)

    def format_title(self):
        return f"{self.display_name}"

    def set_selected(self, selected: bool):
        if self.is_selected != selected:
            self.is_selected = selected
            if selected:
                self.add_class("selected")
            else:
                self.remove_class("selected")
            self.update(self.format_title())


class FeedsWidget(Static):
    """Widget for display feeds in modals"""

    def __init__(self, feed_id: str, feed_details: Dict, type: str, **kwargs):
        self.feed_id = feed_id
        self.feed_name = feed_details["feed_name"]
        self.display_name = feed_details["display_name"]
        self.is_selected = False
        self.symbol = "+" if type == "subscribe" else "-"

        formatted_title = self.format_title()
        super().__init__(formatted_title, **kwargs)

    def format_title(self):
        return f"{self.symbol} {self.display_name}"

    def set_selected(self, selected: bool):
        if self.is_selected != selected:
            self.is_selected = selected
            if selected:
                self.add_class("selected")
            else:
                self.remove_class("selected")
            self.update(self.format_title())


class InputWidget(Input):
    BINDINGS = [
        Binding(
            key="escape",
            action="exit_search_mode",
            description="exit search",
            show=False,
        )
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.disabled = True
        self.display = False

    def action_exit_search_mode(self):
        self.disabled = True

        footer = self.app.query_one(Footer)
        footer.remove_class("hidden")

        search_widget = self.app.query_one("#search-widget", Label)
        search_widget.add_class("hidden")

    def on_input_changed(self):
        search_widget = self.app.query_one("#search-widget", Label)
        escaped_value = self.value.replace("[", r"\[")
        search_widget.update(" /" + escaped_value)
        if (
            len(self.value) > 2
            and " --" not in self.value
            and not self.value.endswith("-")
        ):
            if hasattr(self, "_search_timer") and self._search_timer:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.3, self.prepare_search_request)
            self.prepare_search_request()

    def on_input_submitted(self):
        self.disabled = True
        self.prepare_search_request()

    def prepare_search_request(self):
        if self.value.endswith("-"):
            return

        parts = self.value.split(" --")
        params = {}

        if parts and parts[0]:
            params["search_query"] = parts[0]
        else:
            return

        if len(parts) >= 2:
            for i in range(1, len(parts)):
                param = parts[i]
                if ":" in param:
                    k, v = param.split(":", 1)
                    params[k] = v.strip()
                elif param.strip():
                    params[param.strip()] = True

        self.app.notify(f"{params}")
