import os
from textual.app import App, ComposeResult
from textual.widgets import Footer, Label
from textual.binding import Binding
from textual.containers import Container

from src.terminal_ui.subscription import SubscriptionManager
from src.terminal_ui.widgets import (
    InputWidget,
    TimeDisplay,
    MarketsContainer,
    ArticlesContainer,
    ChannelHeader,
)
from src.terminal_ui.auth import AuthManager
from src.terminal_ui.modals import ArticleModal, SubscribeModal


class TUINews(App):
    """Simple teletext inspired app"""

    CSS_PATH = "styles.css"
    BINDINGS = [
        Binding(key="q", action="quit", description="quit"),
        Binding(key="r", action="refresh", description="refresh"),
        Binding(key="enter", action="open_article", description="confirm"),
        Binding(key="s", action="subscribe", description="subscribe"),
        Binding(key="u", action="unsubscribe", description="unsubscribe"),
        Binding(key="h", action="previous_page", description="left", show=False),
        Binding(key="j", action="move_down", description="down", show=False),
        Binding(key="k", action="move_up", description="up", show=False),
        Binding(key="l", action="next_page", description="right", show=False),
        Binding(key="/", action="search", description="search"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_manager = AuthManager()
        self.subscription_manager = SubscriptionManager(auth_manager=self.auth_manager)
        self.terminal_size = os.get_terminal_size()
        self.motion_count = ""

    async def on_mount(self) -> None:
        """Initialize app"""
        success = await self.auth_manager.authenticate()

        if not success:
            success = await self.auth_manager.authenticate("testuser", "Testpass123")
        if success:
            articles_container = self.query_one("#articles", ArticlesContainer)
            articles_container.terminal_height = self.terminal_size.lines
            articles_container.terminal_width = self.terminal_size.columns
            articles_container.params["limit"] = (
                self.terminal_size.lines - 9
            )  # leaves an empty space before footer
            self.call_later(articles_container.fetch_articles)
            await self.subscription_manager.fetch_subscription_data()
        else:
            self.notify("Login failed. Press 'l' to login manually.", severity="error")

    def on_resize(self) -> None:
        self.terminal_size = os.get_terminal_size()
        articles_container = self.query_one("#articles", ArticlesContainer)
        articles_container.terminal_height = self.terminal_size.lines
        articles_container.terminal_width = self.terminal_size.columns
        articles_container.params["limit"] = (
            self.terminal_size.lines - 9
        )  # leaves an empty space before footer
        self.call_later(articles_container.fetch_articles)

    def action_login(self):
        self.call_later(self.do_login)

    async def do_login(self):
        success = await self.auth_manager.authenticate("testuser", "Testpass123")

        if success:
            self.notify("Login successful", severity="information")
        else:
            self.notify("Login failed.", severity="error")

    def action_refresh(self):
        self.call_later(self.do_refresh)

        channel_header = self.query_one("#channel-header", ChannelHeader)
        channel_header.set_new_articles(0)

    async def do_refresh(self):
        if not self.auth_manager.is_token_valid():
            success = await self.auth_manager.refresh_access_token()
            if not success:
                success = await self.auth_manager.authenticate()
                if not success:
                    self.notify(
                        "Authentication expired. Please login again", severity="error"
                    )
                    return
        articles_container = self.query_one("#articles", ArticlesContainer)
        articles_container.params.pop("cursor", None)
        articles_container.cursor_history = []
        await articles_container.fetch_articles()

        channel_header = self.query_one("#channel-header", ChannelHeader)
        channel_header.update_refresh_time()
        channel_header.set_new_articles(0)

    def on_key(self, event):
        """Handle key events for vim-like motions"""
        if self.app.screen.is_modal:
            return

        key = event.key

        input_widget = self.query_one("#input-widget", InputWidget)
        if not input_widget.disabled and len(input_widget.value) == 0:
            if key == "backspace":
                input_widget.action_exit_search_mode()

        if key.isdigit() and not key.startswith("f"):
            self.motion_count += key
            return

        if key in ["j", "k"]:
            count = int(self.motion_count) if self.motion_count else 1
            self.motion_count = ""

            articles = self.query_one("#articles", ArticlesContainer)
            current_index = articles.selected_index

            if key == "j":
                new_index = min(
                    current_index + count, len(articles.article_widgets) - 1
                )
                articles.select_article(new_index)
            elif key == "k":
                new_index = max(current_index - count, 0)
                articles.select_article(new_index)

            event.prevent_default()
            return

    def action_move_up(self):
        """Move selection up"""
        articles = self.query_one("#articles", ArticlesContainer)
        articles.select_previous_article()

    def action_move_down(self):
        """Move selection down"""
        articles = self.query_one("#articles", ArticlesContainer)
        articles.select_next_article()

    def action_open_article(self):
        """Open the selected article"""
        articles = self.query_one("#articles", ArticlesContainer)
        article = articles.get_selected_article()
        if article:
            self.push_screen(ArticleModal(article))

    def action_subscribe(self):
        """Open subscription interface"""
        modal = SubscribeModal(
            self.subscription_manager,
            on_subscription_change=self.do_refresh,
        )
        modal.all_feeds = self.subscription_manager.all_feeds
        modal.my_feeds = self.subscription_manager.my_feeds
        modal.type = "subscribe"
        self.push_screen(modal)

    def action_unsubscribe(self):
        modal = SubscribeModal(
            self.subscription_manager,
            on_subscription_change=self.do_refresh,
        )
        modal.all_feeds = self.subscription_manager.all_feeds
        modal.my_feeds = self.subscription_manager.my_feeds
        modal.type = "unsubscribe"
        self.push_screen(modal)

    async def action_next_page(self):
        articles_container = self.query_one("#articles", ArticlesContainer)
        if articles_container.next_cursor:
            if articles_container.cursor_history:
                articles_container.cursor_history.append(
                    articles_container.params["cursor"]
                )
            else:
                articles_container.cursor_history.append(None)
            articles_container.params["cursor"] = articles_container.next_cursor
            await articles_container.fetch_articles()

    async def action_previous_page(self):
        articles_container = self.query_one("#articles", ArticlesContainer)
        if articles_container.cursor_history:
            previous_cursor = articles_container.cursor_history.pop()
            if previous_cursor:
                articles_container.params["cursor"] = previous_cursor
            else:
                articles_container.params.pop("cursor", None)
            await articles_container.fetch_articles()

    def action_search(self):
        footer = self.query_one(Footer)
        footer.add_class("hidden")

        search_widget = self.query_one("#search-widget", Label)
        search_widget.remove_class("hidden")
        search_widget.update(" /")

        input_widget = self.query_one("#input-widget", InputWidget)
        input_widget.disabled = False
        input_widget.value = ""
        input_widget.focus()

    def compose(self) -> ComposeResult:
        """create child widgets for app"""
        yield Container(
            TimeDisplay(id="clock"),
            MarketsContainer(id="markets"),
            ChannelHeader("Latest News", id="channel-header"),
            ArticlesContainer(id="articles"),
            id="main-container",
        )
        yield Label(" /", id="search-widget", classes="hidden")
        yield InputWidget(id="input-widget")
        yield Footer()
