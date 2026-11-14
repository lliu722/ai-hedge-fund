"""
Regression tests for LIVE BOT code paths that only fail when actually called.

Why this file exists
--------------------
On 2026-08-10 an audit change added `timeout=_SEND_TIMEOUT` to
telegram_bot.send_message() but defined that constant only in notify.py.
The bot crash-looped in production on its own startup "online" message.

Every check in place at the time passed:
  - syntax check              -> module parses
  - `pytest tests/`           -> 118 passed
  - smoke check               -> `import tools; len(tools)` == 49

All three only proved the module IMPORTS. None of them ever CALLED the
function, and Python resolves module-level names at call time, not import
time. So the whole class of "works on import, NameError on first real use"
was invisible.

These tests call the live paths with the network stubbed. They are
deliberately about *execution*, not behaviour — if they ever feel redundant,
that means the code has stopped changing, not that the risk went away.
"""
import pytest


class _FakeResponse:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {"ok": True, "result": []}


@pytest.fixture
def stub_network(monkeypatch):
    """Capture outbound HTTP instead of sending it. Returns the call list."""
    calls = []

    def fake_request(url, **kwargs):
        calls.append({"url": url, "timeout": kwargs.get("timeout")})
        return _FakeResponse()

    import src.tools.telegram_bot as tb
    import src.tools.notify as nt

    monkeypatch.setattr(tb.requests, "post", fake_request)
    monkeypatch.setattr(nt.requests, "post", fake_request)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    return calls


def test_telegram_bot_send_message_executes(stub_network):
    """send_message() must actually run — this is the exact call that crash-looped."""
    import src.tools.telegram_bot as tb
    tb.send_message("regression test", chat_id="1", show_buttons=True)
    assert stub_network, "send_message made no HTTP call"


def test_telegram_bot_answer_callback_executes(stub_network):
    import src.tools.telegram_bot as tb
    tb.answer_callback("callback-id")
    assert stub_network, "answer_callback made no HTTP call"


def test_notify_send_paths_execute(stub_network):
    import src.tools.notify as nt
    assert nt.send_telegram("regression test") is True
    assert nt.send_telegram_with_buttons(
        "regression test", [[{"text": "X", "callback_data": "x"}]]
    ) is True


def test_every_outbound_send_has_a_client_timeout(stub_network):
    """
    No Telegram send may go out without a client-side socket timeout.

    Two separate production incidents on 2026-08-10 came from missing
    timeouts: getUpdates() hung forever and silently wedged the message
    loop, and the same gap existed on the send side, where a stall would
    wedge the SCHEDULER thread and stop every future alert with nothing
    logged.
    """
    import src.tools.telegram_bot as tb
    import src.tools.notify as nt

    tb.send_message("t", chat_id="1")
    tb.answer_callback("cb")
    nt.send_telegram("t")
    nt.send_telegram_with_buttons("t", [[{"text": "X", "callback_data": "x"}]])

    assert stub_network, "no sends were captured"
    untimed = [c for c in stub_network if c["timeout"] is None]
    assert not untimed, f"sends dispatched with no timeout: {untimed}"


def test_pnl_pct_never_reports_a_negative_basis_winner_as_a_loss():
    """
    Zhipu (2513.HK) holds a real negative cost basis (-1000.40). Dividing by
    it flips the sign, which rendered the book's biggest winner as -229.4%.
    pnl_pct must return None (callers render "n/a"), never a number.
    """
    from src.tools.prices import pnl_pct

    assert pnl_pct(1295.0, -1000.4) is None
    assert pnl_pct(100.0, 0) is None
    assert pnl_pct(100.0, None) is None
    assert pnl_pct(None, 50.0) is None
    # a normal position still computes
    assert pnl_pct(481.6, 579.33) == pytest.approx(-16.87, abs=0.1)


def test_tradable_symbol_filters_non_equities():
    """
    Junk/non-equity rows must never reach yfinance: they 404 every cycle,
    burn quota on calls that can never succeed, and hide real errors.
    """
    from src.tools.prices import tradable_symbol

    for good in ("NVDA", "0700.HK", "GLD", "TPZ.TO"):
        assert tradable_symbol(good), f"{good} should be tradable"
    for bad in (".VIX", "^HSI", "^KS11", "MATIC", "SOL", "BTC", "— (SECTOR)", ""):
        assert tradable_symbol(bad) is None, f"{bad} should be filtered out"


def test_acknowledgements_are_not_treated_as_tickers():
    """"ok"/"sure"/"thanks" are real tickers (OK, ON, IT...) — must not be looked up."""
    from src.tools.telegram_bot import _ACK_ONLY

    for ack in ("ok", "OK", "Ok!", "sure", "thanks", "no", "right"):
        assert ack.strip().lower().rstrip("!.?~ ") in _ACK_ONLY
    for real in ("ON", "deep dive ON", "add CIFR", "price of IT"):
        assert real.strip().lower().rstrip("!.?~ ") not in _ACK_ONLY


def test_worker_maintenance_prunes_only_finished_download_threads(monkeypatch):
    from threading import Event, Thread

    import multitasking
    from src.tools import scheduler

    stop = Event()
    running = Thread(target=stop.wait)
    finished = Thread(target=lambda: None)
    pending = Thread(target=lambda: None)
    finished.start()
    finished.join()
    running.start()
    tasks = [finished, running, pending]
    monkeypatch.setitem(multitasking.config, "TASKS", tasks)
    try:
        scheduler._maintain_worker_memory()
        assert multitasking.get_list_of_tasks() == [running, pending]
        pending.start()
        pending.join()
        scheduler._maintain_worker_memory()
        assert multitasking.get_list_of_tasks() == [running]
    finally:
        stop.set()
        running.join()


def test_scheduled_holdings_reload_refreshes_running_bot(monkeypatch):
    from src.tools import notion_holdings, scheduler, telegram_bot

    held = {"shares": 10}
    watch = {"shares": 0}
    data = {"MSFT": held, "NVDA": watch}
    monkeypatch.setattr(notion_holdings, "reload_holdings", lambda: data)
    monkeypatch.setattr(scheduler, "WATCHLIST_DATA", {})
    monkeypatch.setattr(scheduler, "WATCHLIST", [])
    monkeypatch.setattr(telegram_bot, "WATCHLIST", {"OLD": held})
    monkeypatch.setattr(telegram_bot, "WATCHLIST_TICKERS", ["OLD"])
    monkeypatch.setattr(telegram_bot, "WATCHLIST_TICKERS_SET", {"OLD"})
    monkeypatch.setattr(telegram_bot, "PORTFOLIO", {"OLD": held})
    monkeypatch.setattr(telegram_bot, "WATCHLIST_ONLY", {})

    scheduler.auto_reload_holdings(telegram_bot.refresh_holdings)

    assert scheduler.WATCHLIST_DATA == telegram_bot.WATCHLIST == data
    assert telegram_bot.WATCHLIST_TICKERS == ["MSFT", "NVDA"]
    assert telegram_bot.WATCHLIST_TICKERS_SET == {"MSFT", "NVDA"}
    assert telegram_bot.PORTFOLIO == {"MSFT": held}
    assert telegram_bot.WATCHLIST_ONLY == {"NVDA": watch}


def test_fast_quotes_keep_provider_work_bounded_and_preserve_symbol_results(monkeypatch):
    from threading import Lock
    from time import sleep

    import pandas as pd
    from src.tools import prices

    active = peak = 0
    gate = Lock()

    def history(ticker, **kwargs):
        nonlocal active, peak
        with gate:
            active += 1
            peak = max(peak, active)
        try:
            sleep(0.015)
            if ticker.ticker == "BROKEN":
                raise TimeoutError
            if ticker.ticker == "ONE":
                return pd.DataFrame({"Close": [99.0]})
            return pd.DataFrame({"Close": [100.0, 105.0]})
        finally:
            with gate:
                active -= 1

    monkeypatch.setattr(prices.yf.Ticker, "history", history)
    tickers = [f"TEST{i}" for i in range(120)] + ["0700.HK", "700.HK", "BROKEN", "ONE"]
    quotes = prices._fetch_batch_fast(tickers)

    assert 1 < peak <= 12
    assert set(quotes) == set(tickers)
    assert quotes["0700.HK"] == quotes["700.HK"] == quotes["TEST119"]
    assert quotes["TEST119"]["price"] == 105.0
    assert quotes["TEST119"]["change_pct"] == 5.0
    assert quotes["BROKEN"] == {}
    assert quotes["ONE"]["change_pct"] == 0
