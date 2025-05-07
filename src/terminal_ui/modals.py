import os
import httpx
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Grid, Horizontal, ScrollableContainer
from textual.widgets import Label, ListView, ListItem, Static
from textual.binding import Binding

from src.utils.text_utils import clean_html_for_textual
from src.constants import RSS_FEEDS
from src.core.logging import LogContext, setup_logging


class ArticleModal(ModalScreen):
    """Modal screen to display article summary"""

    CSS_PATH = "modal01.tcss"
    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def __init__(self, article):
        super().__init__()
        self.article = article
        self.article_description = clean_html_for_textual(article["description"])
        self.url = None

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.article["title"], id="modal-title"),
            Label(f"By: {self.article['author']}", id="modal-author"),
            Label(self.article["formatted_pubDate"], id="modal-pubdate"),
            Container(
                Label(
                    f"({self.article['display_name']}) -- {self.article_description}",
                    id="modal-description",
                ),
            ),
            Label(
                f"Source: {self.article['url']} - Press 'o' to open in browser",
                id="modal-url",
            ),
            id="dialog",
        )

    def on_mount(self) -> None:
        self.url = self._format_url()
        url_label = self.query_one("#modal-url", Label)
        url_label.update(f"Source: {self.url} - Press 'o' to open in browser")

    def _format_url(self):
        terminal_width = os.get_terminal_size().columns
        dialog_width = int(terminal_width * 0.75)

        padding = 50
        max_url_length = max(10, dialog_width - padding)
        if len(self.article["url"]) > max_url_length:
            return self.article["url"][:max_url_length] + "..."
        return self.article["url"]


class BaseSubscriptionModal(ModalScreen):
    """Base class for subscription-related modals"""

    CSS_PATH = "modal02.tcss"
    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
        ("enter", "select_action", "Select"),
        ("tab", "switch_panel", "Switch Panel"),
    ]

    def __init__(self):
        setup_logging()
        super().__init__()
        self.logger = LogContext(self.__class__.__name__.lower())
        self.source_map = []
        self.feed_map = []
        self.selected_source = None
        self.selected_feed = None
        self.active_panel = "sources"  # Track which panel is active

    def compose(self) -> ComposeResult:
        yield Container(
            Horizontal(
                Container(
                    ScrollableContainer(
                        ListView(id="sources-list"), id="sources-scroll"
                    ),
                    Static(
                        "Press Tab to switch panels, Enter to select",
                        id="left-instructions",
                    ),
                    id="left-container",
                ),
                Container(
                    ScrollableContainer(ListView(id="feeds-list"), id="feeds-scroll"),
                    Static(self.get_action_instructions(), id="right-instructions"),
                    id="right-container",
                ),
                id="modal-content",
            ),
            id="dialog",
        )

    def get_action_instructions(self):
        """Override in subclasses to provide instructions"""
        return "Select a feed and press Enter to act"

    def get_source_display_name(self, source: str) -> str:
        """Get user-friendly display name for a source"""
        if source in RSS_FEEDS:
            return RSS_FEEDS[source]["display_name"]
        return source.capitalize()

    def format_feed_name(self, name: str) -> str:
        """Format feed name for display"""
        return " ".join(word.capitalize() for word in name.replace("_", " ").split())

    def on_list_view_selected(self, event) -> None:
        """Handle list view selection"""
        list_id = event.list_view.id

        # Only process selections in the active panel
        if list_id == "sources-list" and self.active_panel == "sources":
            selected_index = event.list_view.index
            if 0 <= selected_index < len(self.source_map):
                self.selected_source = self.source_map[selected_index]
                self.selected_feed = None
                self.call_later(self.populate_feeds_list, self.selected_source)

        elif list_id == "feeds-list" and self.active_panel == "feeds":
            selected_index = event.list_view.index
            if self.selected_source and 0 <= selected_index < len(self.feed_map):
                self.selected_feed = self.feed_map[selected_index]

    def highlight_active_panel(self):
        """Update CSS classes to highlight the active panel"""
        left = self.query_one("#left-container")
        right = self.query_one("#right-container")

        if self.active_panel == "sources":
            left.add_class("active-panel")
            right.remove_class("active-panel")
        else:
            right.add_class("active-panel")
            left.remove_class("active-panel")

    def action_switch_panel(self) -> None:
        """Switch between sources and feeds panels"""
        feeds_list = self.query_one("#feeds-list")

        # Only allow switching to feeds panel if there are feeds
        if self.active_panel == "sources" and feeds_list.children:
            self.active_panel = "feeds"
        elif self.active_panel == "feeds":
            self.active_panel = "sources"

        self.highlight_active_panel()

    def action_select_action(self) -> None:
        """Perform the appropriate action based on active panel"""
        if self.active_panel == "sources":
            # If in sources panel, switch to feeds panel if possible
            feeds_list = self.query_one("#feeds-list")
            if feeds_list.children:
                self.action_switch_panel()
        elif self.active_panel == "feeds" and self.selected_feed:
            # If in feeds panel with selection, perform action
            self.call_later(self.perform_action)

    async def perform_action(self):
        """Override in subclasses to perform the appropriate action"""
        pass


class SubscriptionModal(BaseSubscriptionModal):
    """Modal to display subscription interface"""

    def __init__(self):
        super().__init__()
        self.all_feeds = {}
        self.subscribed_feeds = {}

    def get_action_instructions(self):
        return "Press Enter to subscribe to selected feed"

    async def on_mount(self) -> None:
        """Set border titles and load feeds data"""
        left_container = self.query_one("#left-container")
        left_container.border_title = "Sources"

        right_container = self.query_one("#right-container")
        right_container.border_title = "Available Feeds"

        # Set initial active panel
        self.highlight_active_panel()

        # Load data from API
        await self.load_data()

    async def load_data(self) -> None:
        """Load both available feeds and subscribed feeds"""
        try:
            # Get app reference to access auth manager
            app = self.app

            # Check auth
            if (
                not hasattr(app, "auth_manager")
                or not app.auth_manager.is_token_valid()
            ):
                success = await app.auth_manager.refresh_access_token()
                if not success:
                    success = await app.auth_manager.authenticate()
                    if not success:
                        self.notify(
                            "Authentication required to load feeds", severity="error"
                        )
                        return

            # Get auth headers
            headers = app.auth_manager.get_auth_header()

            # Fetch available feeds and subscriptions in parallel
            async with httpx.AsyncClient(timeout=10.0) as client:
                feeds_response = await client.get(
                    "http://127.0.0.1:8000/api/v1/feeds", headers=headers
                )

                my_response = await client.get(
                    "http://127.0.0.1:8000/api/v1/my", headers=headers
                )

                # Process feeds response
                if feeds_response.status_code == 200:
                    self.all_feeds = feeds_response.json()
                else:
                    self.notify(
                        f"Failed to load feeds: {feeds_response.status_code}",
                        severity="error",
                    )
                    return

                # Process subscriptions response
                if my_response.status_code == 200:
                    # Transform the response into the format we need
                    subscribed_data = my_response.json()

                    # Transform subscribed feeds into our desired format
                    self.subscribed_feeds = {}
                    for item in subscribed_data:
                        source = item["source_name"]
                        feed = item["feed_name"]
                        if source not in self.subscribed_feeds:
                            self.subscribed_feeds[source] = []
                        self.subscribed_feeds[source].append(feed)

                    # Populate the sources list
                    await self.populate_sources_list()
                else:
                    self.notify(
                        f"Failed to load subscriptions: {my_response.status_code}",
                        severity="error",
                    )
        except Exception as e:
            self.logger.error(f"Error loading data: {str(e)}")
            self.notify(f"Error loading feed data: {str(e)}", severity="error")

    async def populate_sources_list(self) -> None:
        """Populate the list of sources"""
        try:
            sources_list = self.query_one("#sources-list")
            sources_list.clear()
            self.source_map = []

            # Add sources that have available feeds
            for source in self.all_feeds.keys():
                available_feeds = []

                # Find all unsubscribed feeds for this source
                for feed in self.all_feeds[source]:
                    already_subscribed = (
                        source in self.subscribed_feeds
                        and feed in self.subscribed_feeds[source]
                    )
                    if not already_subscribed:
                        available_feeds.append(feed)

                # Only add source if it has at least one available feed
                if available_feeds:
                    source_display = self.get_source_display_name(source)
                    sources_list.append(ListItem(Label(source_display)))
                    self.source_map.append(source)
                    self.logger.info(
                        f"Added source {source} with {len(available_feeds)} available feeds"
                    )
        except Exception as e:
            self.logger.error(f"Error populating sources list: {str(e)}")
            self.notify(f"Error building sources list: {str(e)}", severity="error")

    async def populate_feeds_list(self, source: str) -> None:
        """Populate the feeds list for a given source"""
        try:
            feeds_list = self.query_one("#feeds-list")
            feeds_list.clear()
            self.feed_map = []

            if source in self.all_feeds:
                # Get all available feeds for this source (that aren't already subscribed)
                for feed in self.all_feeds[source]:
                    # Check if this feed is already subscribed
                    already_subscribed = (
                        source in self.subscribed_feeds
                        and feed in self.subscribed_feeds[source]
                    )

                    # Only add feeds that aren't subscribed
                    if not already_subscribed:
                        feed_display = self.format_feed_name(feed)
                        feeds_list.append(ListItem(Label(feed_display)))
                        self.feed_map.append(feed)
        except Exception as e:
            self.logger.error(f"Error populating feeds list: {str(e)}")
            self.notify(f"Error building feeds list: {str(e)}", severity="error")

    async def perform_action(self) -> None:
        """Subscribe to the currently selected feed"""
        try:
            if not self.selected_source or not self.selected_feed:
                self.notify("No feed selected", severity="warning")
                return

            source = self.selected_source
            feed = self.selected_feed

            # Check authentication
            app = self.app
            if (
                not hasattr(app, "auth_manager")
                or not app.auth_manager.is_token_valid()
            ):
                success = await app.auth_manager.refresh_access_token()
                if not success:
                    self.notify("Authentication required", severity="error")
                    return

            # Call subscribe API
            headers = app.auth_manager.get_auth_header()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"http://127.0.0.1:8000/api/v1/subscribe/{source}/{feed}",
                    headers=headers,
                )

                if response.status_code == 200:
                    # Update local data
                    if source not in self.subscribed_feeds:
                        self.subscribed_feeds[source] = []
                    self.subscribed_feeds[source].append(feed)

                    # Show confirmation
                    self.notify(f"Subscribed to {self.format_feed_name(feed)}")

                    # Repopulate feeds list (to remove the subscribed feed)
                    await self.populate_feeds_list(source)

                    # If no more feeds, update sources list and switch to sources panel
                    feeds_list = self.query_one("#feeds-list")
                    if not feeds_list.children:
                        await self.populate_sources_list()
                        feeds_list.clear()
                        self.active_panel = "sources"
                        self.highlight_active_panel()

                    # Refresh articles if possible
                    if hasattr(app, "do_refresh"):
                        await app.do_refresh()
                else:
                    error_detail = "Unknown error"
                    try:
                        error_data = response.json()
                        error_detail = error_data.get("detail", error_detail)
                    except:
                        pass

                    self.notify(
                        f"Failed to subscribe: {error_detail}", severity="error"
                    )
        except Exception as e:
            self.logger.error(f"Error subscribing: {str(e)}")
            self.notify(f"Error subscribing to feed: {str(e)}", severity="error")


class UnsubscribeModal(BaseSubscriptionModal):
    """Modal to manage unsubscription from feeds"""

    def __init__(self):
        super().__init__()
        self.subscribed_feeds = {}

    def get_action_instructions(self):
        return "Press Enter to unsubscribe from selected feed"

    async def on_mount(self) -> None:
        """Set border titles and load feeds data"""
        left_container = self.query_one("#left-container")
        left_container.border_title = "Sources"

        right_container = self.query_one("#right-container")
        right_container.border_title = "Subscribed Feeds"

        # Set initial active panel
        self.highlight_active_panel()

        # Load data
        await self.load_subscribed_feeds()

    async def load_subscribed_feeds(self) -> None:
        """Load currently subscribed feeds from API"""
        try:
            app = self.app

            # Check auth
            if (
                not hasattr(app, "auth_manager")
                or not app.auth_manager.is_token_valid()
            ):
                success = await app.auth_manager.refresh_access_token()
                if not success:
                    success = await app.auth_manager.authenticate()
                    if not success:
                        self.notify(
                            "Authentication required to load feeds", severity="error"
                        )
                        return

            # Get auth headers
            headers = app.auth_manager.get_auth_header()

            # Fetch subscribed feeds
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "http://127.0.0.1:8000/api/v1/my", headers=headers
                )

                if response.status_code == 200:
                    subscribed_data = response.json()

                    # Transform response to our format
                    self.subscribed_feeds = {}
                    for item in subscribed_data:
                        source = item["source_name"]
                        feed = item["feed_name"]
                        if source not in self.subscribed_feeds:
                            self.subscribed_feeds[source] = []
                        self.subscribed_feeds[source].append(feed)

                    # Populate the sources list
                    await self.populate_sources_list()
                else:
                    self.notify(
                        f"Failed to load subscriptions: {response.status_code}",
                        severity="error",
                    )
        except Exception as e:
            self.logger.error(f"Error loading subscribed feeds: {str(e)}")
            self.notify(f"Error loading subscribed feeds: {str(e)}", severity="error")

    async def populate_sources_list(self) -> None:
        """Populate the list of subscribed sources"""
        try:
            sources_list = self.query_one("#sources-list")
            sources_list.clear()
            self.source_map = []

            # Add each source with subscribed feeds
            for source in self.subscribed_feeds.keys():
                source_display = self.get_source_display_name(source)
                sources_list.append(ListItem(Label(source_display)))
                self.source_map.append(source)
        except Exception as e:
            self.logger.error(f"Error populating sources list: {str(e)}")
            self.notify(f"Error building sources list: {str(e)}", severity="error")

    async def populate_feeds_list(self, source: str) -> None:
        """Populate the feeds list for a given source"""
        try:
            feeds_list = self.query_one("#feeds-list")
            feeds_list.clear()
            self.feed_map = []

            if source in self.subscribed_feeds:
                # Get all subscribed feeds for this source
                for feed in self.subscribed_feeds[source]:
                    feed_display = self.format_feed_name(feed)
                    feeds_list.append(ListItem(Label(feed_display)))
                    self.feed_map.append(feed)
        except Exception as e:
            self.logger.error(f"Error populating feeds list: {str(e)}")
            self.notify(f"Error building feeds list: {str(e)}", severity="error")

    async def perform_action(self) -> None:
        """Unsubscribe from the currently selected feed"""
        try:
            if not self.selected_source or not self.selected_feed:
                self.notify("No feed selected", severity="warning")
                return

            source = self.selected_source
            feed = self.selected_feed

            # Check authentication
            app = self.app
            if (
                not hasattr(app, "auth_manager")
                or not app.auth_manager.is_token_valid()
            ):
                success = await app.auth_manager.refresh_access_token()
                if not success:
                    self.notify("Authentication required", severity="error")
                    return

            # Call unsubscribe API
            headers = app.auth_manager.get_auth_header()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"http://127.0.0.1:8000/api/v1/unsubscribe/{source}/{feed}",
                    headers=headers,
                )

                if response.status_code == 200:
                    # Update local data
                    if (
                        source in self.subscribed_feeds
                        and feed in self.subscribed_feeds[source]
                    ):
                        self.subscribed_feeds[source].remove(feed)
                        # Remove source if no feeds remain
                        if not self.subscribed_feeds[source]:
                            del self.subscribed_feeds[source]

                    # Show confirmation
                    self.notify(f"Unsubscribed from {self.format_feed_name(feed)}")

                    # Repopulate feeds list (to remove the unsubscribed feed)
                    await self.populate_feeds_list(source)

                    # If no more feeds for this source, update sources list and switch to sources panel
                    feeds_list = self.query_one("#feeds-list")
                    if not feeds_list.children:
                        await self.populate_sources_list()
                        feeds_list.clear()
                        self.active_panel = "sources"
                        self.highlight_active_panel()

                    # Refresh articles if possible
                    if hasattr(app, "do_refresh"):
                        await app.do_refresh()
                else:
                    error_detail = "Unknown error"
                    try:
                        error_data = response.json()
                        error_detail = error_data.get("detail", error_detail)
                    except:
                        pass

                    self.notify(
                        f"Failed to unsubscribe: {error_detail}", severity="error"
                    )
        except Exception as e:
            self.logger.error(f"Error unsubscribing: {str(e)}")
            self.notify(f"Error unsubscribing from feed: {str(e)}", severity="error")
