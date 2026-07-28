import json
from collections import defaultdict

import pandas as pd
import requests
import streamlit as st
from apify_client import ApifyClient
import app_secrets as _s
from config import OPENROUTER_API_KEY
from utils import to_excel


APIFY_API_TOKEN = getattr(_s, "FB_GROUPS_APIFY_API_TOKEN", "")
SCRAPER_ENGINE_GROUPS_ACTOR_ID = "scraper-engine/facebook-groups-search-scraper"
EASYAPI_GROUPS_ACTOR_ID = "easyapi/facebook-groups-search-scraper"
SIMPLEAPI_GROUPS_ACTOR_ID = "simpleapi/facebook-groups-search-scraper"
SCRAPIO_GROUPS_ACTOR_ID = "scrapio/facebook-groups-search-scraper"


def parse_entries(raw_text: str) -> list[str]:
    values = []
    seen = set()
    for part in raw_text.replace("\r", "\n").split("\n"):
        for chunk in part.split(","):
            value = chunk.strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
    return values


def build_run_input(start_urls: list[str], max_items: int) -> dict:
    return {
        "startUrls": start_urls,
        "maxItems": int(max_items),
    }


def build_easyapi_run_input(search_query: str, max_items: int) -> dict:
    return {
        "searchQuery": search_query,
        "maxItems": int(max_items),
    }


def run_starturls_groups_actor(actor_id: str, start_urls: list[str], max_items: int) -> tuple[list[dict], dict]:
    if not APIFY_API_TOKEN:
        raise RuntimeError("Apify API token not found in config.")

    client = ApifyClient(APIFY_API_TOKEN)
    run_input = build_run_input(start_urls, max_items)
    run = client.actor(actor_id).call(run_input=run_input)
    status = run.get("status") if isinstance(run, dict) else getattr(run, "status", "UNKNOWN")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Actor failed with status: {status}")

    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", None)
    items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
    return items, run_input


def run_easyapi_groups_actor(search_query: str, max_items: int) -> tuple[list[dict], dict]:
    if not APIFY_API_TOKEN:
        raise RuntimeError("Apify API token not found in config.")

    client = ApifyClient(APIFY_API_TOKEN)
    run_input = build_easyapi_run_input(search_query, max_items)
    run = client.actor(EASYAPI_GROUPS_ACTOR_ID).call(run_input=run_input)
    status = run.get("status") if isinstance(run, dict) else getattr(run, "status", "UNKNOWN")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Actor failed with status: {status}")

    dataset_id = run.get("defaultDatasetId") if isinstance(run, dict) else getattr(run, "default_dataset_id", None)
    items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
    return items, run_input


def build_groups_dataframe(items: list[dict]) -> pd.DataFrame:
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Query": item.get("query", ""),
                "Group ID": item.get("id", ""),
                "Group Name": item.get("name", ""),
                "URL": item.get("url", ""),
                "Visibility": item.get("visibility", ""),
                "Members": item.get("memberInfo", ""),
                "Post Frequency": item.get("postFrequency", ""),
                "Type": item.get("type", ""),
                "Join State": item.get("viewerJoinState", ""),
                "Profile Picture": item.get("profilePictureUri", ""),
            }
        )
    return pd.DataFrame(rows)


def build_grouped_raw_output(items: list[dict], run_input: dict) -> dict:
    grouped = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        query = item.get("query") or "direct_urls"
        grouped[query].append(item)

    results = []
    for query, groups in grouped.items():
        results.append(
            {
                "query": query,
                "groups": groups,
                "count": len(groups),
            }
        )

    return {
        "config": {
            "maxItems": run_input.get("maxItems"),
            "searchQuery": run_input.get("startUrls", []),
        },
        "total_groups": len(items),
        "results": results,
    }


def build_easyapi_raw_output(items: list[dict], run_input: dict) -> dict:
    return {
        "config": run_input,
        "total_groups": len(items),
        "items": items,
    }


def _get_ai_keyword_suggestions(keyword: str) -> list[str]:
    try:
        base_keywords = parse_entries(keyword)
        if not base_keywords:
            return []
        prompt = f"""You are a keyword expansion assistant.
Main keyword: "{base_keywords[0]}"
Generate exactly 10 related search keywords.
Rules:
- Short 1-4 words each
- Highly relevant to the main keyword
- Include close variations, sub-niches, audience terms, and related intent
- No duplicates
- Return ONLY a JSON array of strings
- No explanation, no markdown, no backticks

Example output:
["real estate investing", "property investment", "rental properties"]"""

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openrouter/auto",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.7
            },
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content")
            or ""
        ).strip()
        if not content:
            return []
        content = content.replace("```json", "").replace("```", "").strip()
        if not content.startswith("[") and "[" in content and "]" in content:
            content = content[content.find("["):content.rfind("]") + 1]
        suggestions = json.loads(content)
        return [str(s).strip() for s in suggestions[:10] if s]

    except Exception:
        return []


def _render_ai_pills(target_key: str):
    suggestions = st.session_state.get("fbg_ai_suggestions", [])
    if not suggestions:
        return

    st.caption("Click to add keywords:")
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"]:has(> .element-container .fbg-pill-marker) {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: wrap !important;
            gap: 8px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> .element-container .fbg-pill-marker) > .element-container {
            width: auto !important;
            flex: 0 0 auto !important;
        }
        div[data-testid="stVerticalBlock"]:has(> .element-container .fbg-pill-marker) .stButton > button {
            border-radius: 20px !important;
            padding: 4px 14px !important;
            min-height: 32px !important;
            height: 32px !important;
            font-size: 13px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def toggle_suggestion(suggestion: str, is_selected: bool):
        entries = parse_entries(st.session_state.get(target_key, ""))
        if is_selected:
            st.session_state["fbg_ai_selected"].discard(suggestion)
            entries = [entry for entry in entries if entry != suggestion]
        else:
            st.session_state["fbg_ai_selected"].add(suggestion)
            if suggestion not in entries:
                entries.append(suggestion)
        st.session_state[target_key] = ", ".join(entries)

    with st.container():
        st.markdown("<span class='fbg-pill-marker' style='display:none'></span>", unsafe_allow_html=True)
        for i, suggestion in enumerate(suggestions):
            is_selected = suggestion in st.session_state.get("fbg_ai_selected", set())
            st.button(
                f"✓ {suggestion}" if is_selected else suggestion,
                key=f"fbg_suggest_{i}",
                width="content",
                type="primary" if is_selected else "secondary",
                on_click=toggle_suggestion,
                args=(suggestion, is_selected),
            )


def render():
    if "fbg_ai_suggestions" not in st.session_state:
        st.session_state["fbg_ai_suggestions"] = []
    if "fbg_ai_selected" not in st.session_state:
        st.session_state["fbg_ai_selected"] = set()

    st.title("Facebook Groups Extractor (Apify)")
    st.write("Search Facebook groups by keyword or direct group URL using Apify.")
    st.write("")

    c1, c2, c3 = st.columns([1.3, 4, 1])

    with c1:
        search_type = st.selectbox(
            "Search Type",
            [
                "Keyword / Group URL (Scraper Engine)",
                "Keyword / Group URL (SimpleAPI)",
                "Keyword / Group URL (Scrapio)",
                "Keyword Search (EasyAPI)",
            ],
            key="fb_groups_search_type",
        )

    with c2:
        if search_type in (
            "Keyword / Group URL (Scraper Engine)",
            "Keyword / Group URL (SimpleAPI)",
            "Keyword / Group URL (Scrapio)",
        ):
            search_input = st.text_input(
                "Search Input",
                placeholder="Enter keywords or full Facebook group URLs, comma separated",
                key="fb_groups_search_input",
            )
        else:
            search_input = st.text_input(
                "Search Query",
                placeholder="e.g. tesla",
                key="fb_groups_easyapi_search_query",
            )

        ai_cols = st.columns([1, 5])
        with ai_cols[0]:
            enhance_btn = st.button("✨ AI Enhance", key="fb_groups_ai_enhance_btn")

    with c3:
        max_items = st.selectbox(
            "Max Items",
            options=[1, 2, 3, 5, 10, 20, 50, 100, 200, 500],
            index=5,
            key="fb_groups_max_items",
        )

    active_input_key = (
        "fb_groups_search_input"
        if search_type in (
            "Keyword / Group URL (Scraper Engine)",
            "Keyword / Group URL (SimpleAPI)",
            "Keyword / Group URL (Scrapio)",
        )
        else "fb_groups_easyapi_search_query"
    )

    if not st.session_state.get(active_input_key, "").strip():
        st.session_state["fbg_ai_suggestions"] = []
        st.session_state["fbg_ai_selected"] = set()

    if enhance_btn:
        base_text = st.session_state.get(active_input_key, "").strip()
        if not base_text:
            st.warning("Please type a keyword first.")
        else:
            with st.spinner("Generating suggestions..."):
                suggestions = _get_ai_keyword_suggestions(base_text)
            st.session_state["fbg_ai_suggestions"] = suggestions
            st.session_state["fbg_ai_selected"] = set()
            st.rerun()

    _render_ai_pills(active_input_key)

    if search_type in (
        "Keyword / Group URL (Scraper Engine)",
        "Keyword / Group URL (SimpleAPI)",
        "Keyword / Group URL (Scrapio)",
    ):
        st.caption(
            "Mix keywords and full Facebook group URLs in one run. "
            "`maxItems` applies to keyword searches; direct URLs are scraped directly."
        )
    else:
        st.caption(
            "Search Facebook groups by a single keyword using the EasyAPI actor. "
            "`maxItems` stops the actor when the limit is reached."
        )

    search_btn = st.button("Search", type="primary", key="fb_groups_search_btn")
    st.divider()

    if search_btn:
        try:
            if search_type in (
                "Keyword / Group URL (Scraper Engine)",
                "Keyword / Group URL (SimpleAPI)",
                "Keyword / Group URL (Scrapio)",
            ):
                entries = parse_entries(search_input)
                if not entries:
                    st.warning("Please enter at least one keyword or Facebook group URL.")
                    return

                with st.spinner(f"Running Apify actor for {len(entries)} input value(s)..."):
                    actor_id = {
                        "Keyword / Group URL (Scraper Engine)": SCRAPER_ENGINE_GROUPS_ACTOR_ID,
                        "Keyword / Group URL (SimpleAPI)": SIMPLEAPI_GROUPS_ACTOR_ID,
                        "Keyword / Group URL (Scrapio)": SCRAPIO_GROUPS_ACTOR_ID,
                    }[search_type]
                    items, run_input = run_starturls_groups_actor(actor_id, entries, max_items)
                    raw_output = build_grouped_raw_output(items, run_input)
            else:
                query = search_input.strip()
                if not query:
                    st.warning("Please enter a keyword for EasyAPI search.")
                    return

                with st.spinner(f"Running EasyAPI actor for keyword: {query}"):
                    items, run_input = run_easyapi_groups_actor(query, max_items)
                    raw_output = build_easyapi_raw_output(items, run_input)

            st.session_state["fb_groups_items"] = items
            st.session_state["fb_groups_run_input"] = run_input
            st.session_state["fb_groups_raw_output"] = raw_output
            st.session_state["fb_groups_df"] = build_groups_dataframe(items)
        except Exception as exc:
            st.error(f"Error: {exc}")
            return

    if "fb_groups_df" not in st.session_state:
        st.write("Enter keywords or group URLs above, then click **Search**.")
        return

    df: pd.DataFrame = st.session_state["fb_groups_df"]
    raw_output = st.session_state.get("fb_groups_raw_output", {})

    m1, m2 = st.columns(2)
    with m1:
        st.metric("Total Groups", len(df))
    with m2:
        st.metric("Unique Queries", len({str(x).strip() for x in df.get("Query", pd.Series(dtype=str)).tolist() if str(x).strip()}))

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "Download CSV",
            data=df.to_csv(index=False),
            file_name="facebook_groups.csv",
            mime="text/csv",
            use_container_width=True,
            key="fb_groups_download_csv",
        )
    with d2:
        st.download_button(
            "Download Excel",
            data=to_excel(df),
            file_name="facebook_groups.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="fb_groups_download_excel",
        )
    with d3:
        st.download_button(
            "Download JSON",
            data=json.dumps(raw_output, indent=2, ensure_ascii=False),
            file_name="facebook_groups.json",
            mime="application/json",
            use_container_width=True,
            key="fb_groups_download_json",
        )

    st.divider()

    tab_table, tab_raw = st.tabs(["Table View", "Raw JSON"])
    with tab_table:
        st.dataframe(df, use_container_width=True, height=520)
    with tab_raw:
        st.json(raw_output)


if __name__ == "__main__":
    render()
