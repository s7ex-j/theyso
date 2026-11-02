from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from theyso import power
from theyso.agents.base import AgentEvent, safe_prefix
from theyso.power import KeepAwake
from theyso.service import load_secrets_env, plan_install, run


# ── keep-awake ───────────────────────────────────────────────────────────────
class FakeAwake(KeepAwake):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls: list[str] = []

    def _acquire(self) -> None:
        self.calls.append("acquire")
        self.held = True

    def release(self) -> None:
        if self.held:
            self.calls.append("release")
        self.held = False


def test_keep_awake_follows_sessions_and_charger(monkeypatch: pytest.MonkeyPatch):
    ac = {"on": True}
    monkeypatch.setattr(power, "on_ac_power", lambda: ac["on"])
    k = FakeAwake("sessions", ac_only=True)
    k.update(0)
    assert k.calls == []
    k.update(1)
    k.update(2)
    assert k.calls == ["acquire"]          # one lock, no matter how many sessions
    ac["on"] = False
    k.update(2)
    assert k.calls == ["acquire", "release"]  # unplugged → let it sleep
    ac["on"] = True
    k.update(1)
    k.update(0)
    assert k.calls == ["acquire", "release", "acquire", "release"]


def test_keep_awake_modes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(power, "on_ac_power", lambda: True)
    never, always = FakeAwake("never"), FakeAwake("always")
    never.update(5)
    always.update(0)
    assert never.calls == [] and always.calls == ["acquire"]


# ── service + secrets ────────────────────────────────────────────────────────
def test_secrets_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    f = tmp_path / "secrets.env"
    f.write_text("# comment\nexport TT_A='one'\nTT_B=two\nTT_EXISTING=file\nbroken line\nTT_EMPTY=\n")
    if sys.platform != "win32":
        os.chmod(f, 0o644)
    monkeypatch.setenv("TT_EXISTING", "env-wins")
    monkeypatch.delenv("TT_A", raising=False)
    monkeypatch.delenv("TT_B", raising=False)
    warnings = load_secrets_env(f)
    assert os.environ["TT_A"] == "one" and os.environ["TT_B"] == "two"
    assert os.environ["TT_EXISTING"] == "env-wins" and "TT_EMPTY" not in os.environ
    if sys.platform != "win32":
        assert warnings  # 0644 is flagged


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd plan")
def test_service_plan_linux_dry_run(tmp_path: Path):
    plan = plan_install(tmp_path)
    assert plan.content and "-m theyso serve --log-file auto" in plan.content.replace('"', "")
    assert f"THEYSO_HOME={tmp_path}" in plan.content
    log = run(plan, install=True, dry_run=True)
    assert log[0].startswith("write") and not plan.file.exists()  # dry run touches nothing


# ── streaming ────────────────────────────────────────────────────────────────
def test_safe_prefix_never_leaks_half_a_word():
    assert safe_prefix("my key is sk-ant-api0") == "my key is "
    assert safe_prefix("hello world\nnext") == "hello world\n"
    assert safe_prefix("nospace") == ""


async def test_partial_events_are_ephemeral(state):
    from theyso.sessions import Session

    class Sub:
        device_id = "d"

        def __init__(self) -> None:
            self.frames: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.frames.append(payload)

    s = Session("s1", "t", "fake", state.cfg.profiles["fake"], Path("."), state.cfg,
                state.sessions.policy, state.metrics, state.audit)
    sub = Sub()
    s.subscribers.add(sub)
    await s.emit(AgentEvent("partial", {"stream_id": "1:0", "text": "token ghp_" + "x" * 36 + " end "}))
    await s.emit(AgentEvent("text", {"text": "final"}))
    partial, final = sub.frames
    assert "seq" not in partial and "xxxx" not in partial["data"]["text"]  # still redacted
    assert final["seq"] == 1 and len(s.buffer) == 1  # only the final text is history
    await asyncio.sleep(0)


async def test_session_limit_enforced(state):
    from theyso.sessions import SessionError

    state.cfg.server.max_sessions = 2
    await state.sessions.create("fake", "demo", None, None, "dev")
    await state.sessions.create("fake", "demo", None, None, "dev")
    with pytest.raises(SessionError) as exc:
        await state.sessions.create("fake", "demo", None, None, "dev")
    assert exc.value.code == "forbidden"
