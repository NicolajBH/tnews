from textual.app import App, ComposeResult
from textual.widgets import Footer
from textual.binding import Binding
from textual.containers import Container

from src.terminal_ui.widgets import (
    TimeDisplay,
    MarketsContainer,
    ArticlesContainer,
    ChannelHeader,
)
from src.terminal_ui.auth import AuthManager
from src.terminal_ui.modals import ArticleModal, SubscriptionModal, UnsubscribeModal


class TUINews(App):
    """Simple teletext inspired app"""

    CSS_PATH = "styles.css"
    BINDINGS = [
        Binding(key="q", action="quit", description="quit"),
        Binding(key="r", action="refresh", description="refresh"),
        Binding(key="l", action="login", description="login"),
        Binding(key="j", action="move_down", description="down"),
        Binding(key="k", action="move_up", description="up"),
        Binding(key="enter", action="open_article", description="open article"),
        Binding(key="s", action="subscribe", description="subscribe"),
        Binding(key="u", action="unsubscribe", description="unsubscribe"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_manager = AuthManager()

    async def on_mount(self) -> None:
        """Initialize app"""
        success = await self.auth_manager.authenticate()

        if not success:
            success = await self.auth_manager.authenticate("testuser", "Testpass123")
        if success:
            articles_container = self.query_one("#articles", ArticlesContainer)
            self.call_later(articles_container.fetch_articles)
        else:
            self.notify("Login failed. Press 'l' to login manually.", severity="error")

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
        await articles_container.fetch_articles()

        channel_header = self.query_one("#channel-header", ChannelHeader)
        channel_header.update_refresh_time()
        channel_header.set_new_articles(0)

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
        self.push_screen(SubscriptionModal())

    def action_unsubscribe(self):
        """Open unsubscription interface"""
        self.push_screen(UnsubscribeModal())

    def compose(self) -> ComposeResult:
        """create child widgets for app"""
        yield Container(
            TimeDisplay(id="clock"),
            MarketsContainer(id="markets"),
            ChannelHeader("Latest News", id="channel-header"),
            ArticlesContainer(id="articles"),
            id="main-container",
        )
        yield Footer()
