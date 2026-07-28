import os
import json
import logging
import requests
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from apify_client import ApifyClient
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "DataLeads")

SCRAPER_ENGINE_GROUPS_ACTOR_ID = "scraper-engine/facebook-groups-search-scraper"
EASYAPI_GROUPS_ACTOR_ID = "easyapi/facebook-groups-search-scraper"
SIMPLEAPI_GROUPS_ACTOR_ID = "simpleapi/facebook-groups-search-scraper"
SCRAPIO_GROUPS_ACTOR_ID = "scrapio/facebook-groups-search-scraper"

def get_field(obj, key, default=None):
    if not obj:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        pass
    try:
        return getattr(obj, key, default)
    except Exception:
        pass
    return default

db = None
if MONGO_URI and not MONGO_URI.startswith("your_"):
    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client[MONGO_DB_NAME]
        logger.info("Connected to MongoDB successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")

app = FastAPI(title="DataLeads API Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class EnhanceRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=500)

class EnhanceResponse(BaseModel):
    keyword: str
    suggestions: list[str]

class SearchRequest(BaseModel):
    searchType: str = Field(..., min_length=1)
    searchInput: str = Field(..., min_length=1)
    maxItems: int = Field(20, ge=1, le=500)

class GroupItem(BaseModel):
    query: str | None = ""
    id: str | None = ""
    name: str | None = ""
    url: str | None = ""
    visibility: str | None = ""
    members: str | None = ""
    postFrequency: str | None = ""
    type: str | None = ""
    joinState: str | None = ""
    profilePicture: str | None = ""

class SearchResponse(BaseModel):
    total_groups: int
    groups: list[GroupItem]
    raw_output: dict

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

def run_starturls_groups_actor(actor_id: str, start_urls: list[str], max_items: int) -> tuple[list[dict], dict]:
    if not APIFY_API_TOKEN or APIFY_API_TOKEN.startswith("your_"):
        raise RuntimeError("Apify API token not configured.")
    client = ApifyClient(APIFY_API_TOKEN)
    run_input = {
        "startUrls": start_urls,
        "maxItems": int(max_items)
    }
    run = client.actor(actor_id).call(run_input=run_input)
    status_val = get_field(run, "status", "UNKNOWN")
    if status_val != "SUCCEEDED":
        raise RuntimeError(f"Apify actor failed with status: {status_val}")
    dataset_id = get_field(run, "defaultDatasetId") or get_field(run, "default_dataset_id")
    items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
    return items, run_input

def run_easyapi_groups_actor(search_query: str, max_items: int) -> tuple[list[dict], dict]:
    if not APIFY_API_TOKEN or APIFY_API_TOKEN.startswith("your_"):
        raise RuntimeError("Apify API token not configured.")
    client = ApifyClient(APIFY_API_TOKEN)
    run_input = {
        "searchQuery": search_query,
        "maxItems": int(max_items)
    }
    run = client.actor(EASYAPI_GROUPS_ACTOR_ID).call(run_input=run_input)
    status_val = get_field(run, "status", "UNKNOWN")
    if status_val != "SUCCEEDED":
        raise RuntimeError(f"Apify actor failed with status: {status_val}")
    dataset_id = get_field(run, "defaultDatasetId") or get_field(run, "default_dataset_id")
    items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
    return items, run_input

def build_grouped_raw_output(items: list[dict], run_input: dict) -> dict:
    grouped = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        query = item.get("query") or "direct_urls"
        grouped[query].append(item)

    results = []
    for query, groups in grouped.items():
        results.append({
            "query": query,
            "groups": groups,
            "count": len(groups)
        })

    return {
        "config": {
            "maxItems": run_input.get("maxItems"),
            "searchQuery": run_input.get("startUrls", [])
        },
        "total_groups": len(items),
        "results": results
    }

def build_easyapi_raw_output(items: list[dict], run_input: dict) -> dict:
    return {
        "config": run_input,
        "total_groups": len(items),
        "items": items
    }

def build_groups_list(items: list[dict]) -> list[dict]:
    groups = []
    for item in items:
        if not isinstance(item, dict):
            continue
        groups.append({
            "query": item.get("query") or "",
            "id": item.get("id") or "",
            "name": item.get("name") or "",
            "url": item.get("url") or "",
            "visibility": item.get("visibility") or "",
            "members": item.get("memberInfo") or "",
            "postFrequency": item.get("postFrequency") or "",
            "type": item.get("type") or "",
            "joinState": item.get("viewerJoinState") or "",
            "profilePicture": item.get("profilePictureUri") or ""
        })
    return groups

@app.get("/")
def read_root():
    return {"status": "backend running"}

@app.get("/api/debug-token")
def debug_token():
    return {
        "apify_token_prefix": APIFY_API_TOKEN[:10] if APIFY_API_TOKEN else "empty",
        "mongo_db_name": MONGO_DB_NAME
    }

@app.post("/api/enhance", response_model=EnhanceResponse)
def enhance_keyword(payload: EnhanceRequest):
    base_keywords = parse_entries(payload.keyword)
    if not base_keywords:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provided keyword query is empty or invalid."
        )

    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("your_"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OpenRouter AI configuration is missing on the server."
        )

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

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    body = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.7
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=15
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.exception("Failed to connect to OpenRouter API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with OpenRouter AI: {str(e)}"
        )

    try:
        data = response.json()
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content")
            or ""
        ).strip()
        
        if not content:
            raise ValueError("Empty response text from AI completions model.")

        content = content.replace("```json", "").replace("```", "").strip()
        
        if not content.startswith("[") and "[" in content and "]" in content:
            content = content[content.find("["):content.rfind("]") + 1]

        suggestions = json.loads(content)
        if not isinstance(suggestions, list):
            raise ValueError("Parsed content is not a JSON list.")

        cleaned_suggestions = [str(s).strip() for s in suggestions if s][:10]

        return EnhanceResponse(
            keyword=base_keywords[0],
            suggestions=cleaned_suggestions
        )
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.error(f"Failed to parse AI response JSON: {response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Received malformed response from AI: {str(e)}"
        )

@app.post("/api/search", response_model=SearchResponse)
def run_search(payload: SearchRequest):
    try:
        if payload.searchType in ("scraper_engine", "simpleapi", "scrapio"):
            entries = parse_entries(payload.searchInput)
            if not entries:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please enter at least one keyword or Facebook group URL."
                )
            
            actor_id = {
                "scraper_engine": SCRAPER_ENGINE_GROUPS_ACTOR_ID,
                "simpleapi": SIMPLEAPI_GROUPS_ACTOR_ID,
                "scrapio": SCRAPIO_GROUPS_ACTOR_ID,
            }[payload.searchType]
            
            items, run_input = run_starturls_groups_actor(actor_id, entries, payload.maxItems)
            raw_output = build_grouped_raw_output(items, run_input)
            
        elif payload.searchType == "easyapi":
            query = payload.searchInput.strip()
            if not query:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please enter a keyword query for EasyAPI."
                )
                
            items, run_input = run_easyapi_groups_actor(query, payload.maxItems)
            raw_output = build_easyapi_raw_output(items, run_input)
            
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown search type: {payload.searchType}"
            )
            
        groups_list = build_groups_list(items)
        
        if db is not None:
            try:
                run_doc = {
                    "search_type": payload.searchType,
                    "search_input": payload.searchInput,
                    "max_items": payload.maxItems,
                    "timestamp": datetime.utcnow(),
                    "total_groups": len(items),
                    "groups": groups_list,
                    "raw_output": raw_output
                }
                db.fb_groups_extractor.insert_one(run_doc)
            except Exception as e:
                logger.error(f"Failed to save search run to MongoDB: {e}")

        return SearchResponse(
            total_groups=len(items),
            groups=groups_list,
            raw_output=raw_output
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)
        )