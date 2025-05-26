import os
import webbrowser

from textual.widgets import Label
from textual.binding import Binding
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Grid, VerticalScroll

from terminal_ui.widgets import FeedsWidget, SourceWidget
from utils.text_utils import clean_html_for_textual


class ArticleModal(ModalScreen):
    """Modal screen to display article summary"""

    CSS_PATH = "modal01.tcss"
    BINDINGS = [
        Binding(key="escape", action="dismiss", description="dismiss"),
        Binding(key="enter", action="open_article", description="open article"),
    ]

    def __init__(self, article):
        super().__init__()
        self.article = article
        self.article_description = clean_html_for_textual(article["description"])
        self.article_url = article["url"]
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
        url_label.update(f"Source: {self.url} - Press '⏎' to open in browser")

    def _format_url(self):
        terminal_width = os.get_terminal_size().columns
        dialog_width = int(terminal_width * 0.75)

        padding = 50
        max_url_length = max(10, dialog_width - padding)
        if len(self.article["url"]) > max_url_length:
            return self.article["url"][:max_url_length] + "..."
        return self.article["url"]

    def action_open_article(self) -> None:
        if self.article_url:
            webbrowser.open(self.article_url)


class SubscribeModal(ModalScreen):
    CSS_PATH = "modal02.tcss"
    BINDINGS = [
        Binding(key="escape", action="dismiss", description="dismiss"),
        Binding(key="j", action="move_down", description="down"),
        Binding(key="k", action="move_up", description="up"),
        Binding(key="l", action="move_right", description="right"),
        Binding(key="h", action="move_left", description="left"),
        Binding(key="enter", action="select", description="select feed"),
    ]

    def __init__(self, subscription_manager, on_subscription_change=None) -> None:
        super().__init__()
        self.my_feeds = {}
        self.all_feeds = {}
        self.data = {}
        self.type = ""
        self.sources_list = None
        self.feeds_list = None
        self.selected_source_index = 0
        self.selected_feed_index = 0
        self.active_pane = "sources"
        self.subscription_manager = subscription_manager
        self.on_subscription_change = on_subscription_change

    def on_mount(self) -> None:
        self.sources_list = VerticalScroll(id="left-pane", classes="pane active-pane")
        self.sources_list.border_title = "Sources"

        self.feeds_list = VerticalScroll(id="right-pane", classes="pane inactive-pane")
        self.feeds_list.border_title = "Feeds"

        self.subscription_container = Container(
            self.sources_list, self.feeds_list, id="app-grid"
        )

        self.mount(self.subscription_container)
        self.refresh()
        self.call_after_refresh(self.update_data)

    def select_source(self, index: int) -> None:
        if not self.sources_widgets:
            return

        index = max(0, min(index, len(self.sources_widgets) - 1))

        # Deselect current selection
        if 0 <= self.selected_source_index < len(self.sources_widgets):
            self.sources_widgets[self.selected_source_index].set_selected(False)

        # Select new article
        self.selected_source_index = index
        self.sources_widgets[self.selected_source_index].set_selected(True)

        # Ensure the selected source is visible
        try:
            self.sources_widgets[self.selected_source_index].scroll_visible()
        except Exception as e:
            self.app.log(f"Error scrolling: {e}")

    def select_feed(self, index: int) -> None:
        if not self.feeds_widgets:
            return

        index = max(0, min(index, len(self.feeds_widgets) - 1))

        # Deselect current selection
        if 0 <= self.selected_feed_index < len(self.feeds_widgets):
            self.feeds_widgets[self.selected_feed_index].set_selected(False)

        # Select new article
        self.selected_feed_index = index
        self.feeds_widgets[self.selected_feed_index].set_selected(True)

        # Ensure the selected source is visible
        try:
            self.feeds_widgets[self.selected_feed_index].scroll_visible()
        except Exception as e:
            self.app.log(f"Error scrolling: {e}")

    def action_move_down(self) -> None:
        """Select the next article"""
        if self.active_pane == "sources":
            if (
                self.sources_widgets
                and self.selected_source_index < len(self.sources_widgets) - 1
            ):
                self.select_source(self.selected_source_index + 1)
                self.update_feeds()

        if self.active_pane == "feeds":
            if (
                self.feeds_widgets
                and self.selected_feed_index < len(self.feeds_widgets) - 1
            ):
                self.select_feed(self.selected_feed_index + 1)

    def action_move_up(self) -> None:
        """Select the previous item"""
        if self.active_pane == "sources":
            if self.sources_widgets and self.selected_source_index > 0:
                self.select_source(self.selected_source_index - 1)
                self.update_feeds()

        if self.active_pane == "feeds":
            if self.feeds_widgets and self.selected_feed_index > 0:
                self.select_feed(self.selected_feed_index - 1)

    def action_move_right(self) -> None:
        """Switch pane to feeds"""
        self.active_pane = "feeds"

        active_pane = self.query_one("#left-pane")
        inactive_pane = self.query_one("#right-pane")

        active_pane.remove_class("active-pane").add_class("inactive-pane")
        inactive_pane.remove_class("inactive-pane").add_class("active-pane")

    def action_move_left(self) -> None:
        self.active_pane = "sources"

        active_pane = self.query_one("#right-pane")
        inactive_pane = self.query_one("#left-pane")

        active_pane.remove_class("active-pane").add_class("inactive-pane")
        inactive_pane.remove_class("inactive-pane").add_class("active-pane")

    def update_sources(self):
        if self.sources_list is not None:
            self.sources_list.remove_children()

        if not self.data:
            return

        self.sources_widgets = []
        for k, feed_data in self.data.items():
            widget = SourceWidget(k, feed_data)
            self.sources_widgets.append(widget)
            self.sources_list.mount(widget)

        self.refresh()
        if self.sources_widgets:
            self.call_after_refresh(self.select_source, self.selected_source_index)

    def update_feeds(self):
        if self.feeds_list is not None:
            self.feeds_list.remove_children()

        if not self.data:
            return

        self.feeds_widgets = []
        source = self.sources_widgets[self.selected_source_index].source_name
        for feed_id, feed_details in self.data[source]["feeds"].items():
            widget = FeedsWidget(feed_id, feed_details, self.type)
            self.feeds_widgets.append(widget)
            self.feeds_list.mount(widget)
        self.refresh()
        if self.feeds_widgets:
            self.call_after_refresh(self.select_feed, self.selected_feed_index)

    def update_data(self):
        self.data = {}

        if self.type == "unsubscribe":
            for k, v in self.my_feeds.items():
                if v["source_name"] not in self.data:
                    self.data[v["source_name"]] = {
                        "source_name": v["source_name"],
                        "display_name": self.all_feeds["sources"][v["source_name"]][
                            "display_name"
                        ],
                        "feeds": {
                            k: {
                                "feed_name": v["feed_name"],
                                "display_name": v["display_name"],
                            }
                        },
                    }
                else:
                    self.data[v["source_name"]]["feeds"][k] = {
                        "feed_name": v["feed_name"],
                        "display_name": v["display_name"],
                    }
        elif self.type == "subscribe":
            for k, v in self.all_feeds["sources"].items():
                for feed in v["feeds"]:
                    if feed["id"] not in self.my_feeds:
                        if k not in self.data:
                            self.data[k] = {
                                "source_name": k,
                                "display_name": v["display_name"],
                                "feeds": {
                                    feed["id"]: {
                                        "feed_name": feed["feed_name"],
                                        "display_name": feed["display_name"],
                                    }
                                },
                            }
                        else:
                            self.data[k]["feeds"][feed["id"]] = {
                                "feed_name": feed["feed_name"],
                                "display_name": feed["display_name"],
                            }

        self.update_sources()
        self.update_feeds()

    async def action_select(self) -> None:
        """Get the currently selected feed data"""
        if hasattr(self, "feeds_widgets") and 0 <= self.selected_feed_index < len(
            self.feeds_widgets
        ):
            if self.active_pane == "feeds":
                source = self.sources_widgets[self.selected_source_index].source_name
                feed = self.feeds_widgets[self.selected_feed_index].feed_name
                display_name = self.feeds_widgets[self.selected_feed_index].display_name
                await self.update_subscriptions(source, feed, display_name)
            else:
                self.action_move_right()
        return None

    async def update_subscriptions(
        self, source: str, feed: str, display_name: str
    ) -> None:
        success = False
        if self.type == "subscribe":
            self.my_feeds[f"{source}:{feed}"] = {
                "source_name": source,
                "feed_name": feed,
                "display_name": display_name,
            }
            response = await self.subscription_manager.subscribe(source, feed)
            if response == 200:
                success = True
            else:
                self.app.notify(
                    f"Failed to subscribe to {source}/{feed}. Response code {response}"
                )
        elif self.type == "unsubscribe":
            del self.my_feeds[f"{source}:{feed}"]
            response = await self.subscription_manager.unsubscribe(source, feed)
            if response == 200:
                success = True
            else:
                self.app.notify(
                    f"Failed to unsubscribe from {source}/{feed}. Response code {response}"
                )
        self.feeds_widgets.pop(self.selected_feed_index)
        if len(self.feeds_widgets) > 0:
            self.selected_feed_index -= 1
        else:
            if self.selected_source_index > 0:
                self.selected_source_index -= 1
            self.selected_feed_index = 0
            self.action_move_left()

        self.update_data()
        self.update_sources()
        self.update_feeds()
        self.refresh()

        if success and self.on_subscription_change:
            self.app.call_after_refresh(self.on_subscription_change)

        if self.feeds_widgets:
            self.call_after_refresh(self.select_feed, self.selected_feed_index)
        if self.sources_widgets:
            self.call_after_refresh(self.select_source, self.selected_source_index)
