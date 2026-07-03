from core.vision.ui_parser import UIParser


def test_parse_extracts_xml_when_device_logs_prefix_output():
    xml = """java.io.FileNotFoundException: noisy MIUI stderr
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="抖音" resource-id="com.miui.home:id/icon_title" class="android.widget.TextView" content-desc="" bounds="[287,895][541,971]" clickable="false" enabled="true" focused="false" />
</hierarchy>
UI hierchary dumped to: /dev/tty
"""

    elements = UIParser().parse(xml)

    assert len(elements) == 1
    assert elements[0].text == "抖音"


def test_infer_screen_treats_android_launcher_as_launcher_not_search():
    xml = """<hierarchy rotation="0">
  <node text="搜索" resource-id="com.miui.home:id/search_bar" class="android.widget.TextView" content-desc="搜索框" bounds="[0,0][100,100]" />
  <node text="抖音" resource-id="com.miui.home:id/icon_title" class="android.widget.TextView" content-desc="" bounds="[0,100][100,200]" />
</hierarchy>"""
    parser = UIParser()
    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.miui.home",
        activity="com.miui.home.launcher.Launcher",
    )

    assert state.screen == "launcher"
    assert state.confidence >= 0.8


def test_infer_screen_blocks_when_dm_requires_peer_reply():
    state = UIParser().infer_screen(
        [],
        ocr_text="为保障用户沟通安全，未互相关注的陌生人违规消息可能会被处理\n对方回复后才能发消息",
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.splash.SplashActivity",
    )

    assert state.screen == "blocked"
    assert state.blocker == "dm_unavailable"


def test_infer_screen_allows_one_message_warning_for_unfollowed_chat():
    state = UIParser().infer_screen(
        [],
        ocr_text="为保障用户沟通安全，未互相关注的陌生人违规消息可能会被处理\n只能发送一条消息",
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.splash.SplashActivity",
    )

    assert state.blocker == ""
    assert state.screen != "blocked"


def test_infer_screen_blocks_on_english_login_required_text():
    state = UIParser().infer_screen(
        [],
        ocr_text="Please log in again. Your session has expired.",
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.splash.SplashActivity",
    )

    assert state.screen == "blocked"
    assert state.blocker == "login_required"


def test_infer_screen_blocks_on_english_risk_control_text():
    state = UIParser().infer_screen(
        [],
        ocr_text="Too many operations. Try again later. Account restricted.",
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.splash.SplashActivity",
    )

    assert state.screen == "blocked"
    assert state.blocker == "risk_control"


def test_infer_screen_detects_douyin_search_result_list():
    xml = """<hierarchy rotation="0">
  <node text="Search" resource-id="com.ss.android.ugc.aweme:id/search_box" class="android.widget.EditText" clickable="true" enabled="true" />
  <node text="Users" resource-id="com.ss.android.ugc.aweme:id/tab_user" class="android.widget.TextView" clickable="true" enabled="true" />
  <node text="target_account" resource-id="com.ss.android.ugc.aweme:id/user_name" class="android.widget.TextView" clickable="true" enabled="true" />
  <node text="Follow" resource-id="com.ss.android.ugc.aweme:id/follow_btn" class="android.widget.Button" clickable="true" enabled="true" />
</hierarchy>"""
    parser = UIParser()

    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.search.SearchResultActivity",
    )

    assert state.screen == "search_results"
    assert state.confidence >= 0.85


def test_infer_screen_detects_profile_dm_button_ready():
    xml = """<hierarchy rotation="0">
  <node text="Followers" resource-id="com.ss.android.ugc.aweme:id/follower_count" class="android.widget.TextView" />
  <node text="Works" resource-id="com.ss.android.ugc.aweme:id/work_count" class="android.widget.TextView" />
  <node text="Message" resource-id="com.ss.android.ugc.aweme:id/message_button" class="android.widget.Button" clickable="true" enabled="true" />
</hierarchy>"""
    parser = UIParser()

    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.profile.ProfileActivity",
    )

    assert state.screen == "profile_dm_ready"
    assert state.blocker == ""


def test_infer_screen_detects_dm_button_unavailable():
    xml = """<hierarchy rotation="0">
  <node text="Followers" resource-id="com.ss.android.ugc.aweme:id/follower_count" class="android.widget.TextView" />
  <node text="Message unavailable" resource-id="com.ss.android.ugc.aweme:id/message_button" class="android.widget.Button" clickable="false" enabled="false" />
</hierarchy>"""
    parser = UIParser()

    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.profile.ProfileActivity",
    )

    assert state.screen == "dm_unavailable"
    assert state.blocker == "dm_unavailable"


def test_infer_screen_detects_disabled_chat_input():
    xml = """<hierarchy rotation="0">
  <node text="Private message" resource-id="com.ss.android.ugc.aweme:id/title" class="android.widget.TextView" />
  <node text="Input message" resource-id="com.ss.android.ugc.aweme:id/message_input" class="android.widget.EditText" clickable="false" enabled="false" />
  <node text="Send" resource-id="com.ss.android.ugc.aweme:id/send_button" class="android.widget.Button" clickable="false" enabled="false" />
</hierarchy>"""
    parser = UIParser()

    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.im.ChatActivity",
    )

    assert state.screen == "chat_input_disabled"
    assert state.blocker == "dm_unavailable"


def test_infer_screen_detects_sent_message_bubble():
    xml = """<hierarchy rotation="0">
  <node text="Private message" resource-id="com.ss.android.ugc.aweme:id/title" class="android.widget.TextView" />
  <node text="hello from automation" resource-id="com.ss.android.ugc.aweme:id/message_bubble" class="android.widget.TextView" />
  <node text="Sent" resource-id="com.ss.android.ugc.aweme:id/message_status" class="android.widget.TextView" />
</hierarchy>"""
    parser = UIParser()

    state = parser.infer_screen(
        parser.parse(xml),
        package_name="com.ss.android.ugc.aweme",
        activity="com.ss.android.ugc.aweme.im.ChatActivity",
    )

    assert state.screen == "message_sent"
    assert state.confidence >= 0.85
