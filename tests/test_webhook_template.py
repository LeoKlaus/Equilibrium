import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from api.models.webhook_body_format import WebhookBodyFormat
from hub.event_bus import Event
from webhooks.template import PLACEHOLDERS, build_values, render, render_header, template_problems

JSON = WebhookBodyFormat.JSON
TEXT = WebhookBodyFormat.TEXT

NOW = datetime(2026, 11, 14, 20, 30, 5, tzinfo=UTC)


def _values(event_type="scene.started", **payload):
    payload = {"scene_id": 3, "scene_name": "Movie Night", **payload}
    return build_values(Event(event_type, payload), "Living Room", NOW)


def test_build_values_describes_a_scene_event():
    assert _values() == {
        "EVENT": "scene.started",
        "TIMESTAMP": "2026-11-14T20:30:05Z",
        "INSTANCE_NAME": "Living Room",
        "SCENE_ID": "3",
        "SCENE_NAME": "Movie Night",
        "SCENE_STATUS": "active",
    }


def test_build_values_covers_every_placeholder():
    assert set(_values()) == set(PLACEHOLDERS)


@pytest.mark.parametrize(
    ("event_type", "status"),
    [("scene.starting", "starting"), ("scene.started", "active"), ("scene.stopping", "stopping"), ("scene.stopped", "stopped")],
)
def test_build_values_derives_the_scene_status_from_the_event(event_type, status):
    assert _values(event_type)["SCENE_STATUS"] == status


def test_build_values_converts_the_timestamp_to_utc():
    local = datetime(2026, 11, 14, 21, 30, 5, tzinfo=timezone(timedelta(hours=1)))

    values = build_values(Event("scene.started", {}), "Hub", local)

    assert values["TIMESTAMP"] == "2026-11-14T20:30:05Z"


def test_build_values_uses_empty_strings_for_missing_scene_data():
    values = build_values(Event("scene.started", {"scene_id": None, "scene_name": None}), "Hub", NOW)

    assert values["SCENE_ID"] == ""
    assert values["SCENE_NAME"] == ""


def test_build_values_leaves_the_status_empty_for_an_unknown_event():
    assert build_values(Event("something.else", {}), "Hub", NOW)["SCENE_STATUS"] == ""


def test_render_substitutes_placeholders():
    body = '{"scene": {{ SCENE_ID }}, "name": "{{SCENE_NAME}}", "event": "{{   EVENT}}"}'

    assert render(body, _values(), JSON) == '{"scene": 3, "name": "Movie Night", "event": "scene.started"}'


def test_render_substitutes_a_placeholder_more_than_once():
    assert render("{{ SCENE_ID }}-{{ SCENE_ID }}", _values(), JSON) == "3-3"


def test_render_escapes_quotes_backslashes_and_newlines():
    values = _values(scene_name='The "Best"\\Scene\nEver')

    assert render('{"name": "{{ SCENE_NAME }}"}', values, JSON) == '{"name": "The \\"Best\\"\\\\Scene\\nEver"}'


def test_rendered_json_stays_valid_whatever_the_scene_is_called():
    name = 'a"b\\c\n\t\x00 {{ EVENT }} é'
    rendered = render('{"name": "{{ SCENE_NAME }}"}', _values(scene_name=name), JSON)

    assert json.loads(rendered) == {"name": name}


def test_render_keeps_non_ascii_characters_readable():
    assert render("{{ SCENE_NAME }}", _values(scene_name="Café ☕"), JSON) == "Café ☕"


def test_render_does_not_expand_placeholders_inside_values():
    values = _values(scene_name="{{ EVENT }}")

    assert render("{{ SCENE_NAME }}", values, JSON) == "{{ EVENT }}"


def test_render_leaves_unknown_placeholders_as_written():
    assert render("{{ NOPE }} {{ SCENE_ID }}", _values(), JSON) == "{{ NOPE }} 3"


def test_render_is_case_sensitive():
    assert render("{{ scene_id }}", _values(), JSON) == "{{ scene_id }}"


def test_render_leaves_json_braces_alone():
    assert render('{"a": {"b": {{ SCENE_ID }}}}', _values(), JSON) == '{"a": {"b": 3}}'


def test_template_problems_is_empty_for_a_valid_template():
    assert template_problems('{"a": {"b": "{{ SCENE_NAME }}"}} {{EVENT}}') == []


def test_template_problems_reports_unknown_placeholders_once():
    assert template_problems("{{ NOPE }} {{ NOPE }} {{ OTHER }}") == [
        "Unknown placeholder NOPE",
        "Unknown placeholder OTHER",
    ]


@pytest.mark.parametrize("template", ["{{ SCENE_ID", "{{ }}", "{{ SCENE-ID }}", "{{", "a {{ 1 }} b"])
def test_template_problems_reports_a_brace_pair_that_is_not_a_placeholder(template):
    assert template_problems(template) == ['"{{" doesn\'t start a valid placeholder']


def test_text_bodies_keep_values_as_they_are():
    values = _values(scene_name='The "Best"\\Scene\nEver')

    assert render("name: {{ SCENE_NAME }}", values, TEXT) == 'name: The "Best"\\Scene\nEver'


def test_text_bodies_still_leave_unknown_placeholders_as_written():
    assert render("{{ NOPE }} {{ SCENE_ID }}", _values(), TEXT) == "{{ NOPE }} 3"


def test_text_bodies_do_not_expand_placeholders_inside_values():
    assert render("{{ SCENE_NAME }}", _values(scene_name="{{ EVENT }}"), TEXT) == "{{ EVENT }}"


def test_render_header_substitutes_placeholders():
    assert render_header("Bearer-{{ SCENE_ID }}-{{ NOPE }}", _values()) == "Bearer-3-{{ NOPE }}"


def test_render_header_replaces_line_breaks_and_control_characters_with_spaces():
    values = _values(scene_name="a\r\nX-Injected: yes\x00b")

    assert render_header("{{ SCENE_NAME }}", values) == "a  X-Injected: yes b"


def test_render_header_does_not_escape_quotes():
    assert render_header("{{ SCENE_NAME }}", _values(scene_name='say "hi"')) == 'say "hi"'
