import os
import webbrowser
from platform import platform
from typing import Any

import pytest

from zulipterminal.core import Controller
from zulipterminal.version import ZT_VERSION


MODULE = "zulipterminal.core"
MODEL = MODULE + ".Model"

SERVER_URL = "https://chat.zulip.zulip"


class TestController:
    @pytest.fixture(autouse=True)
    def mock_external_classes(self, mocker: Any) -> None:
        mocker.patch("zulipterminal.ui_tools.boxes.MessageBox.main_view")
        self.client = mocker.patch("zulip.Client")
        # Patch init only, in general, allowing specific patching elsewhere
        self.model = mocker.patch(MODEL + ".__init__", return_value=None)
        self.view = mocker.patch(MODULE + ".View.__init__", return_value=None)
        self.model.view = self.view
        self.view.focus_col = 1

    @pytest.fixture
    def controller(self, mocker) -> None:
        # Patch these unconditionally to avoid calling in __init__
        self.poll_for_events = mocker.patch(MODEL + ".poll_for_events")
        mocker.patch(MODULE + ".Controller.show_loading")
        self.main_loop = mocker.patch(
            MODULE + ".urwid.MainLoop", return_value=mocker.Mock()
        )

        self.config_file = "path/to/zuliprc"
        self.theme_name = "zt_dark"
        self.theme = "default"
        self.in_explore_mode = False
        self.autohide = True  # FIXME Add tests for no-autohide
        self.notify_enabled = False
        self.maximum_footlinks = 3
        result = Controller(
            self.config_file,
            self.maximum_footlinks,
            self.theme_name,
            self.theme,
            256,
            self.in_explore_mode,
            self.autohide,
            self.notify_enabled,
        )
        result.view.message_view = mocker.Mock()  # set in View.__init__
        result.model.server_url = SERVER_URL
        return result

    def test_initialize_controller(self, controller, mocker) -> None:
        self.client.assert_called_once_with(
            config_file=self.config_file,
            client="ZulipTerminal/" + ZT_VERSION + " " + platform(),
        )
        self.model.assert_called_once_with(controller)
        self.view.assert_called_once_with(controller)
        self.poll_for_events.assert_called_once_with()
        assert controller.theme == self.theme
        assert controller.maximum_footlinks == self.maximum_footlinks
        assert self.main_loop.call_count == 1
        controller.loop.watch_pipe.assert_has_calls(
            [
                mocker.call(controller._draw_screen),
                mocker.call(controller._raise_exception),
            ]
        )

    def test_initial_editor_mode(self, controller):
        assert not controller.is_in_editor_mode()

    def test_current_editor_error_if_no_editor(self, controller):
        with pytest.raises(AssertionError):
            controller.current_editor()

    def test_editor_mode_entered_from_initial(self, mocker, controller):
        editor = mocker.Mock()

        controller.enter_editor_mode_with(editor)

        assert controller.is_in_editor_mode()
        assert controller.current_editor() == editor

    def test_editor_mode_error_on_multiple_enter(self, mocker, controller):
        controller.enter_editor_mode_with(mocker.Mock())

        with pytest.raises(AssertionError):
            controller.enter_editor_mode_with(mocker.Mock())

    def test_editor_mode_exits_after_entering(self, mocker, controller):
        controller.enter_editor_mode_with(mocker.Mock())
        controller.exit_editor_mode()

        assert not controller.is_in_editor_mode()

    def test_narrow_to_stream(
        self, mocker, controller, stream_button, index_stream
    ) -> None:
        controller.model.narrow = []
        controller.model.index = index_stream
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.stream_dict = {
            205: {
                "color": "#ffffff",
                "name": "PTEST",
            }
        }
        controller.model.muted_streams = []
        controller.model.is_muted_topic = mocker.Mock(return_value=False)

        controller.narrow_to_stream(stream_name="PTEST")

        assert controller.model.stream_id == stream_button.stream_id
        assert controller.model.narrow == [["stream", stream_button.stream_name]]
        controller.view.message_view.log.clear.assert_called_once_with()

        widget = controller.view.message_view.log.extend.call_args_list[0][0][0][0]
        stream_id = stream_button.stream_id
        id_list = index_stream["stream_msg_ids_by_stream_id"][stream_id]
        assert {widget.original_widget.message["id"]} == id_list

    @pytest.mark.parametrize(
        ["initial_narrow", "initial_stream_id", "anchor", "expected_final_focus"],
        [
            ([], None, None, 537289),
            ([["stream", "PTEST"], ["topic", "Test"]], 205, 537286, 537286),
            ([["stream", "PTEST"], ["topic", "Test"]], 205, 537289, 537289),
        ],
        ids=[
            "all-messages_to_topic_narrow_no_anchor",
            "topic_narrow_to_same_topic_narrow_with_anchor",
            "topic_narrow_to_same_topic_narrow_with_other_anchor",
        ],
    )
    def test_narrow_to_topic(
        self,
        mocker,
        controller,
        msg_box,
        index_multiple_topic_msg,
        initial_narrow,
        initial_stream_id,
        anchor,
        expected_final_focus,
    ):
        expected_narrow = [
            ["stream", msg_box.stream_name],
            ["topic", msg_box.topic_name],
        ]
        controller.model.narrow = initial_narrow
        controller.model.index = index_multiple_topic_msg
        controller.model.stream_id = initial_stream_id
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.stream_dict = {
            205: {
                "color": "#ffffff",
                "name": "PTEST",
            }
        }
        controller.model.muted_streams = []
        controller.model.is_muted_topic = mocker.Mock(return_value=False)

        controller.narrow_to_topic(
            stream_name="PTEST",
            topic_name=msg_box.topic_name,
            contextual_message_id=anchor,
        )

        assert controller.model.stream_id == msg_box.stream_id
        assert controller.model.narrow == expected_narrow
        controller.view.message_view.log.clear.assert_called_once_with()

        widgets, focus = controller.view.message_view.log.extend.call_args_list[0][0]
        stream_id, topic_name = msg_box.stream_id, msg_box.topic_name
        id_list = index_multiple_topic_msg["topic_msg_ids"][stream_id][topic_name]
        msg_ids = {widget.original_widget.message["id"] for widget in widgets}
        final_focus_msg_id = widgets[focus].original_widget.message["id"]
        assert msg_ids == id_list
        assert final_focus_msg_id == expected_final_focus

    def test_narrow_to_user(self, mocker, controller, user_button, index_user):
        controller.model.narrow = []
        controller.model.index = index_user
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.user_id = 5140
        controller.model.user_email = "some@email"
        controller.model.user_dict = {
            user_button.email: {"user_id": user_button.user_id}
        }

        emails = [user_button.email]

        controller.narrow_to_user(recipient_emails=emails)

        assert controller.model.narrow == [["pm_with", user_button.email]]
        controller.view.message_view.log.clear.assert_called_once_with()
        recipients = frozenset([controller.model.user_id, user_button.user_id])
        assert controller.model.recipients == recipients
        widget = controller.view.message_view.log.extend.call_args_list[0][0][0][0]
        id_list = index_user["private_msg_ids_by_user_ids"][recipients]
        assert {widget.original_widget.message["id"]} == id_list

    @pytest.mark.parametrize(
        "anchor, expected_final_focus_msg_id",
        [(None, 537288), (537286, 537286), (537288, 537288)],
    )
    def test_narrow_to_all_messages(
        self,
        mocker,
        controller,
        index_all_messages,
        anchor,
        expected_final_focus_msg_id,
    ):
        controller.model.narrow = [["stream", "PTEST"]]
        controller.model.index = index_all_messages
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.user_email = "some@email"
        controller.model.user_id = 1
        controller.model.stream_dict = {
            205: {
                "color": "#ffffff",
            }
        }
        controller.model.muted_streams = []
        controller.model.is_muted_topic = mocker.Mock(return_value=False)

        controller.narrow_to_all_messages(contextual_message_id=anchor)

        assert controller.model.narrow == []
        controller.view.message_view.log.clear.assert_called_once_with()

        widgets, focus = controller.view.message_view.log.extend.call_args_list[0][0]
        id_list = index_all_messages["all_msg_ids"]
        msg_ids = {widget.original_widget.message["id"] for widget in widgets}
        final_focus_msg_id = widgets[focus].original_widget.message["id"]
        assert msg_ids == id_list
        assert final_focus_msg_id == expected_final_focus_msg_id

    def test_narrow_to_all_pm(self, mocker, controller, index_user):
        controller.model.narrow = []
        controller.model.index = index_user
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.user_id = 1
        controller.model.user_email = "some@email"

        controller.narrow_to_all_pm()  # FIXME: Add id narrowing test

        assert controller.model.narrow == [["is", "private"]]
        controller.view.message_view.log.clear.assert_called_once_with()

        widgets = controller.view.message_view.log.extend.call_args_list[0][0][0]
        id_list = index_user["private_msg_ids"]
        msg_ids = {widget.original_widget.message["id"] for widget in widgets}
        assert msg_ids == id_list

    def test_narrow_to_all_starred(self, mocker, controller, index_all_starred):
        controller.model.narrow = []
        controller.model.index = index_all_starred
        controller.model.muted_streams = set()  # FIXME Expand upon this
        controller.model.user_id = 1
        # FIXME: Expand upon is_muted_topic().
        controller.model.is_muted_topic = mocker.Mock(return_value=False)
        controller.model.user_email = "some@email"
        controller.model.stream_dict = {
            205: {
                "color": "#ffffff",
            }
        }
        controller.view.message_view = mocker.patch("urwid.ListBox")

        controller.narrow_to_all_starred()  # FIXME: Add id narrowing test

        assert controller.model.narrow == [["is", "starred"]]
        controller.view.message_view.log.clear.assert_called_once_with()

        id_list = index_all_starred["starred_msg_ids"]
        widgets = controller.view.message_view.log.extend.call_args_list[0][0][0]
        msg_ids = {widget.original_widget.message["id"] for widget in widgets}
        assert msg_ids == id_list

    def test_narrow_to_all_mentions(self, mocker, controller, index_all_mentions):
        controller.model.narrow = []
        controller.model.index = index_all_mentions
        controller.model.muted_streams = set()  # FIXME Expand upon this
        # FIXME: Expand upon is_muted_topic().
        controller.model.is_muted_topic = mocker.Mock(return_value=False)
        controller.model.user_email = "some@email"
        controller.model.user_id = 1
        controller.model.stream_dict = {
            205: {
                "color": "#ffffff",
            }
        }
        controller.view.message_view = mocker.patch("urwid.ListBox")

        controller.narrow_to_all_mentions()  # FIXME: Add id narrowing test

        assert controller.model.narrow == [["is", "mentioned"]]
        controller.view.message_view.log.clear.assert_called_once_with()

        id_list = index_all_mentions["mentioned_msg_ids"]
        widgets = controller.view.message_view.log.extend.call_args_list[0][0][0]
        msg_ids = {widget.original_widget.message["id"] for widget in widgets}
        assert msg_ids == id_list

    @pytest.mark.parametrize(
        "url",
        [
            "https://chat.zulip.org/#narrow/stream/test",
            "https://chat.zulip.org/user_uploads/sent/abcd/efg.png",
            "https://github.com/",
        ],
    )
    def test_open_in_browser_success(self, mocker, controller, url):
        # Set DISPLAY environ to be able to run test in CI
        os.environ["DISPLAY"] = ":0"
        controller.report_success = mocker.Mock()
        mock_get = mocker.patch(MODULE + ".webbrowser.get")
        mock_open = mock_get.return_value.open

        controller.open_in_browser(url)

        mock_open.assert_called_once_with(url)
        controller.report_success.assert_called_once_with(
            f"The link was successfully opened using {mock_get.return_value.name}"
        )

    def test_open_in_browser_fail__no_browser_controller(self, mocker, controller):
        os.environ["DISPLAY"] = ":0"
        error = "No runnable browser found"
        controller.report_error = mocker.Mock()
        mocker.patch(MODULE + ".webbrowser.get").side_effect = webbrowser.Error(error)

        controller.open_in_browser("https://chat.zulip.org/#narrow/stream/test")

        controller.report_error.assert_called_once_with(f"ERROR: {error}")

    def test_main(self, mocker, controller):
        controller.view.palette = {"default": "theme_properties"}
        mock_tsk = mocker.patch(MODULE + ".Screen.tty_signal_keys")
        controller.loop.screen.tty_signal_keys = mocker.Mock(return_value={})

        controller.main()

        assert controller.loop.run.call_count == 1

    @pytest.mark.parametrize(
        "muted_streams, action", [({205, 89}, "unmuting"), ({89}, "muting")]
    )
    def test_stream_muting_confirmation_popup(
        self, mocker, controller, stream_button, muted_streams, action
    ):
        pop_up = mocker.patch(MODULE + ".PopUpConfirmationView")
        text = mocker.patch(MODULE + ".urwid.Text")
        partial = mocker.patch(MODULE + ".partial")
        controller.model.muted_streams = muted_streams
        controller.loop = mocker.Mock()

        controller.stream_muting_confirmation_popup(stream_button)
        text.assert_called_with(
            ("bold", f"Confirm {action} of stream '{stream_button.stream_name}' ?"),
            "center",
        )
        pop_up.assert_called_once_with(controller, text(), partial())

    @pytest.mark.parametrize(
        "initial_narrow, final_narrow",
        [
            ([], [["search", "FOO"]]),
            ([["search", "BOO"]], [["search", "FOO"]]),
            ([["stream", "PTEST"]], [["stream", "PTEST"], ["search", "FOO"]]),
            (
                [["pm_with", "foo@zulip.com"], ["search", "BOO"]],
                [["pm_with", "foo@zulip.com"], ["search", "FOO"]],
            ),
            (
                [["stream", "PTEST"], ["topic", "RDS"]],
                [["stream", "PTEST"], ["topic", "RDS"], ["search", "FOO"]],
            ),
        ],
        ids=[
            "Default_all_msg_search",
            "redo_default_search",
            "search_within_stream",
            "pm_search_again",
            "search_within_topic_narrow",
        ],
    )
    @pytest.mark.parametrize("msg_ids", [({200, 300, 400}), (set()), ({100})])
    def test_search_message(
        self, initial_narrow, final_narrow, controller, mocker, msg_ids
    ):
        get_message = mocker.patch(MODEL + ".get_messages")
        create_msg = mocker.patch(MODULE + ".create_msg_box_list")
        mocker.patch(MODEL + ".get_message_ids_in_current_narrow", return_value=msg_ids)
        controller.model.index = {"search": {500}}  # Any initial search index
        controller.view.message_view = mocker.patch("urwid.ListBox")
        controller.model.narrow = initial_narrow

        def set_msg_ids(*args, **kwargs):
            controller.model.index["search"].update(msg_ids)

        get_message.side_effect = set_msg_ids
        assert controller.model.index["search"] == {500}

        controller.search_messages("FOO")

        assert controller.model.narrow == final_narrow
        get_message.assert_called_once_with(
            num_after=0, num_before=30, anchor=10000000000
        )
        create_msg.assert_called_once_with(controller.model, msg_ids)
        assert controller.model.index == {"search": msg_ids}

    @pytest.mark.parametrize(
        "screen_size, expected_popup_size",
        [
            ((150, 90), (3 * 150 // 4, 3 * 90 // 4)),
            ((90, 75), (7 * 90 // 8, 3 * 75 // 4)),
            ((70, 60), (70, 3 * 60 // 4)),
        ],
        ids=[
            "above_linear_range",
            "in_linear_range",
            "below_linear_range",
        ],
    )
    def test_maximum_popup_dimensions(
        self, mocker, controller, screen_size, expected_popup_size
    ):
        controller.loop.screen.get_cols_rows = mocker.Mock(return_value=screen_size)

        popup_size = controller.maximum_popup_dimensions()

        assert popup_size == expected_popup_size
