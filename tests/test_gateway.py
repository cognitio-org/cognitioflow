"""The gateway lane: off by default, allow-listed tasks only, personal data replaced before sending."""
import gateway


def on(monkeypatch, **env):
    monkeypatch.setattr(gateway, "_tripped", False)
    for k in ("CF_GATEWAY", "LITELLM_API_KEY", "CF_GATEWAY_SPEND_CEILING", "CF_GATEWAY_TASKS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_off_without_key_or_ceiling(monkeypatch):
    on(monkeypatch)
    assert not gateway.allows("cards")
    on(monkeypatch, LITELLM_API_KEY="k")                    # a key alone is not enough: no budget cap
    assert not gateway.allows("cards")
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113")
    assert gateway.allows("cards")


def test_only_listed_tasks(monkeypatch):
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113")
    for task in ("cards", "concepts", "syllabus", "oral"):
        assert gateway.allows(task)
    for task in ("drill", "explain", "notes", "chat", "", None):
        assert not gateway.allows(task)
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113", CF_GATEWAY_TASKS="cards")
    assert gateway.allows("cards") and not gateway.allows("syllabus")


def test_kill_switch_and_trip(monkeypatch):
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113", CF_GATEWAY="off")
    assert not gateway.allows("cards")
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113")
    monkeypatch.setattr(gateway, "_tripped", True)
    assert not gateway.allows("cards")


def test_call_refuses_unlisted_task_without_network(monkeypatch):
    on(monkeypatch, LITELLM_API_KEY="k", CF_GATEWAY_SPEND_CEILING="113")
    assert gateway.call("drill", max_tokens=10, messages=[{"role": "user", "content": "x"}]) is None


def test_minimise_replaces_personal_data_and_keeps_law():
    text = ("Mail me at matej@mgms.eu or +31 6 1234 5678, IBAN NL91 ABNA 0417 1643 00, student s1234567. "
            "Art. 3:84 DCC, VIII.–2:101(1)(e), C-62/88, [1995] 1 A.C. 74, §929 BGB, 30.8.2007.")
    out = gateway.minimise(text)
    for leaked in ("matej@mgms.eu", "1234 5678", "NL91", "s1234567"):
        assert leaked not in out
    for kept in ("Art. 3:84 DCC", "VIII.–2:101(1)(e)", "C-62/88", "[1995] 1 A.C. 74", "§929 BGB", "30.8.2007"):
        assert kept in out


def test_minimise_messages_leaves_non_text_blocks():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "a@b.co"}, {"type": "image", "source": {}}]}]
    out = gateway._minimise_messages(msgs)
    assert out[0]["content"][0]["text"] == "[email]" and out[0]["content"][1]["type"] == "image"
    assert msgs[0]["content"][0]["text"] == "a@b.co"            # the caller's messages are not mutated
