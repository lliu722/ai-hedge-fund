"""
Theme Momentum Tracker — GitHub commit velocity + arXiv paper volume as
leading indicators of thesis formation, 12-18 months before consensus.

Signal logic:
  GitHub: recent week commits vs 4-week prior average → acceleration ratio
  arXiv:  paper count last 7 days on theme keywords → volume signal
  DeepSeek: synthesise into a one-line signal per theme (Accelerating / Stable / Cooling)
"""
import os
import re
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone


# ── Signal repos per theme ────────────────────────────────────────────────────
# Pick repos that best proxy DEVELOPER activity on each thesis

SIGNAL_REPOS = {
    "AI Infrastructure": [
        ("vllm-project",   "vllm"),           # inference engine — GPU throughput
        ("ggerganov",      "llama.cpp"),       # on-device inference adoption
        ("NVIDIA",         "TensorRT-LLM"),   # NVDA's own inference stack
        ("microsoft",      "DeepSpeed"),       # training efficiency
        ("huggingface",    "transformers"),    # model adoption breadth
    ],
    "Software & Data": [
        ("langchain-ai",   "langchain"),       # AI app development
        ("microsoft",      "autogen"),         # multi-agent frameworks
        ("palantir",       "palantir-python-sdk"),  # AIP adoption proxy
        ("run-llama",      "llama_index"),     # RAG / enterprise AI
    ],
    "Memory Cycle": [
        ("TimDettmers",    "bitsandbytes"),    # memory-efficient inference (proxy for HBM demand pressure)
        ("huggingface",    "peft"),            # parameter-efficient training → lower memory need
    ],
    "Networking & Optical": [
        ("NVIDIA",         "nccl"),            # collective comms — GPU cluster networking
        ("pytorch",        "pytorch"),         # distributed training bandwidth proxy
    ],
    "Quantum": [
        ("Qiskit",         "qiskit"),
        ("quantumlib",     "Cirq"),
    ],
    "Space": [
        ("nasa",           "fprime"),          # NASA flight software — space ecosystem proxy
    ],
}

# ── arXiv search queries per theme ───────────────────────────────────────────

ARXIV_QUERIES = {
    "AI Infrastructure":   "LLM inference GPU training large language model",
    "Software & Data":     "AI agent enterprise LLM application RAG",
    "Memory Cycle":        "memory-efficient training HBM bandwidth quantization",
    "Networking & Optical":"optical interconnect GPU cluster network AI datacenter",
    "Quantum":             "quantum error correction fault tolerant qubit",
    "Space":               "satellite constellation direct cell LEO",
    "Energy & Power":      "AI datacenter power consumption energy efficiency GPU",
}


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _repo_stats(owner: str, repo: str) -> dict:
    """
    Fetch star count and weekly commit velocity for a single repo.
    commit_acceleration = recent_week / prior_4wk_avg (>1.2 = accelerating)
    """
    base = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        # Basic info: stars, forks
        r = requests.get(base, headers=_gh_headers(), timeout=8)
        if r.status_code != 200:
            return {}
        info = r.json()
        stars = info.get("stargazers_count", 0)
        forks = info.get("forks_count", 0)

        # Weekly commit activity (last 52 weeks)
        r2 = requests.get(f"{base}/stats/commit_activity", headers=_gh_headers(), timeout=8)
        acceleration = None
        recent_commits = None
        if r2.status_code == 200:
            weeks = r2.json()
            if isinstance(weeks, list) and len(weeks) >= 5:
                recent = weeks[-1].get("total", 0)
                prior_avg = sum(w.get("total", 0) for w in weeks[-5:-1]) / 4
                recent_commits = recent
                if prior_avg > 0:
                    acceleration = round(recent / prior_avg, 2)

        return {
            "repo": f"{owner}/{repo}",
            "stars": stars,
            "forks": forks,
            "recent_commits": recent_commits,
            "commit_acceleration": acceleration,
        }
    except Exception:
        return {}


def _fetch_theme_repos(theme: str) -> list:
    repos = SIGNAL_REPOS.get(theme, [])
    if not repos:
        return []
    with ThreadPoolExecutor(max_workers=min(len(repos), 5)) as ex:
        results = list(ex.map(lambda r: _repo_stats(r[0], r[1]), repos))
    return [r for r in results if r]


# ── arXiv helpers ─────────────────────────────────────────────────────────────

def _arxiv_count(query: str, days: int = 7) -> int:
    """
    Count arXiv papers submitted in the last `days` days matching `query`.
    Uses the arXiv Atom feed API — no key required.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
        url = (
            "http://export.arxiv.org/search/"
            f"?searchtype=all&query={requests.utils.quote(query)}"
            f"&start=0&max_results=50&order=-announced_date_first"
        )
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return 0

        # Parse Atom XML
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.text)
        entries = root.findall("atom:entry", ns)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0
        for entry in entries:
            published = entry.find("atom:published", ns)
            if published is not None and published.text:
                try:
                    pub_dt = datetime.fromisoformat(published.text.replace("Z", "+00:00"))
                    if pub_dt >= cutoff:
                        count += 1
                except Exception:
                    pass
        return count
    except Exception:
        return 0


# ── Main analysis function ─────────────────────────────────────────────────────

def get_theme_momentum(theme: str = None) -> str:
    """
    Return a momentum signal for one theme or all mapped themes.
    Combines GitHub commit velocity + arXiv paper volume.
    DeepSeek synthesises into Accelerating / Stable / Cooling signal.
    """
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

    themes_to_run = [theme] if theme and theme in SIGNAL_REPOS else list(SIGNAL_REPOS.keys())

    def _analyse_one(t: str) -> str:
        arxiv_q = ARXIV_QUERIES.get(t, "")

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_repos = ex.submit(_fetch_theme_repos, t)
            f_arxiv = ex.submit(_arxiv_count, arxiv_q, 7) if arxiv_q else None
            repo_stats = f_repos.result()
            arxiv_count = f_arxiv.result() if f_arxiv else 0

        if not repo_stats and arxiv_count == 0:
            return f"• <b>{t}</b>: No data available."

        # Build summary text for DeepSeek
        repo_lines = []
        for s in repo_stats:
            acc = s.get("commit_acceleration")
            commits = s.get("recent_commits")
            stars_k = f"{s['stars']/1000:.1f}k" if s.get("stars") else "?"
            acc_str = f"{acc:.1f}x vs 4wk avg" if acc is not None else "no commit data"
            commit_str = f"{commits} commits this week" if commits is not None else ""
            repo_lines.append(f"{s['repo']} ★{stars_k} — {commit_str} ({acc_str})")

        context = "\n".join(repo_lines)

        prompt = (
            f"Theme: {t}\n"
            f"GitHub signal (key repos this week):\n{context}\n"
            f"arXiv papers last 7 days matching '{arxiv_q[:60]}': {arxiv_count}\n\n"
            f"Give ONE line:\n"
            f"[emoji] [theme]: [Accelerating/Stable/Cooling] — [1 specific sentence on what the data shows "
            f"and what it signals for the investment thesis. Be concrete about the numbers.]\n"
            f"Emoji: 🚀 Accelerating, 📊 Stable, ❄️ Cooling\n"
            f"Max 30 words for the sentence."
        )

        try:
            r = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 80, "temperature": 0.2},
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        # Fallback: format raw data
        acc_values = [s["commit_acceleration"] for s in repo_stats if s.get("commit_acceleration")]
        avg_acc = sum(acc_values) / len(acc_values) if acc_values else None
        signal = "🚀 Accelerating" if avg_acc and avg_acc > 1.2 else "❄️ Cooling" if avg_acc and avg_acc < 0.8 else "📊 Stable"
        return f"• <b>{t}</b>: {signal} (avg commit accel {avg_acc:.1f}x · {arxiv_count} arXiv papers/wk)"

    # Run all themes in parallel
    with ThreadPoolExecutor(max_workers=min(len(themes_to_run), 6)) as ex:
        results = list(ex.map(_analyse_one, themes_to_run))

    date_str = datetime.now().strftime("%d %b %Y")
    header = f"📡 <b>Theme Momentum — Developer Signal</b>\n<i>{date_str} · GitHub commit velocity + arXiv volume</i>\n\n"
    body = "\n".join(results)
    footer = "\n\n<i>🚀 Accelerating = thesis forming early · ❄️ Cooling = developer interest waning</i>"
    return header + body + footer


def get_weekly_momentum_digest() -> str:
    """
    Compact version for Sunday weekly digest — just the signal lines, no header.
    """
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    themes = list(SIGNAL_REPOS.keys())

    def _quick_signal(t: str) -> str:
        arxiv_q = ARXIV_QUERIES.get(t, "")
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_repos = ex.submit(_fetch_theme_repos, t)
            f_arxiv = ex.submit(_arxiv_count, arxiv_q, 7) if arxiv_q else None
            repo_stats = f_repos.result()
            arxiv_count = f_arxiv.result() if f_arxiv else 0

        acc_values = [s["commit_acceleration"] for s in repo_stats if s.get("commit_acceleration")]
        avg_acc = round(sum(acc_values) / len(acc_values), 2) if acc_values else None
        emoji = "🚀" if avg_acc and avg_acc > 1.2 else "❄️" if avg_acc and avg_acc < 0.8 else "📊"
        acc_str = f"{avg_acc:.1f}x commits" if avg_acc else "no data"
        return f"{emoji} <b>{t}</b>: {acc_str} · {arxiv_count} papers/wk"

    with ThreadPoolExecutor(max_workers=6) as ex:
        lines = list(ex.map(_quick_signal, themes))

    return "<b>Developer Signal (GitHub + arXiv):</b>\n" + "\n".join(lines)
