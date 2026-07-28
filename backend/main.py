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

class SearchStartResponse(BaseModel):
    run_id: str
    status: str

class SearchResponse(BaseModel):
    status: str
    total_groups: int
    groups: list[GroupItem]
    raw_output: dict
    run_id: str | None = ""
    search_type: str | None = ""
    search_input: str | None = ""
    max_items: int | None = 20

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

def start_starturls_groups_actor(actor_id: str, start_urls: list[str], max_items: int) -> tuple[str, dict]:
    if not APIFY_API_TOKEN or APIFY_API_TOKEN.startswith("your_"):
        raise RuntimeError("Apify API token not configured.")
    client = ApifyClient(APIFY_API_TOKEN)
    run_input = {
        "startUrls": start_urls,
        "maxItems": int(max_items)
    }
    run = client.actor(actor_id).start(run_input=run_input)
    run_id = get_field(run, "id") or get_field(run, "run_id")
    if not run_id:
        raise RuntimeError("Failed to obtain run ID from Apify.")
    return run_id, run_input

def start_easyapi_groups_actor(search_query: str, max_items: int) -> tuple[str, dict]:
    if not APIFY_API_TOKEN or APIFY_API_TOKEN.startswith("your_"):
        raise RuntimeError("Apify API token not configured.")
    client = ApifyClient(APIFY_API_TOKEN)
    run_input = {
        "searchQuery": search_query,
        "maxItems": int(max_items)
    }
    run = client.actor(EASYAPI_GROUPS_ACTOR_ID).start(run_input=run_input)
    run_id = get_field(run, "id") or get_field(run, "run_id")
    if not run_id:
        raise RuntimeError("Failed to obtain run ID from Apify.")
    return run_id, run_input

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

@app.post("/api/search/start", response_model=SearchStartResponse)
def run_search_start(payload: SearchRequest):
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
            run_id, run_input = start_starturls_groups_actor(actor_id, entries, payload.maxItems)
            
        elif payload.searchType == "easyapi":
            query = payload.searchInput.strip()
            if not query:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please enter a keyword query for EasyAPI."
                )
            run_id, run_input = start_easyapi_groups_actor(query, payload.maxItems)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown search type: {payload.searchType}"
            )

        if db is not None:
            try:
                run_doc = {
                    "_id": run_id,
                    "run_id": run_id,
                    "search_type": payload.searchType,
                    "search_input": payload.searchInput,
                    "max_items": payload.maxItems,
                    "status": "RUNNING",
                    "timestamp": datetime.utcnow(),
                    "total_groups": 0,
                    "groups": [],
                    "raw_output": {},
                    "run_input": run_input
                }
                db.fb_groups_extractor.insert_one(run_doc)
            except Exception as e:
                logger.error(f"Failed to save search start to MongoDB: {e}")

        return SearchStartResponse(run_id=run_id, status="RUNNING")

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)
        )

@app.get("/api/search/status/{run_id}", response_model=SearchResponse)
def run_search_status(run_id: str):
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection is unavailable to retrieve status."
        )
    
    run_doc = db.fb_groups_extractor.find_one({"_id": run_id})
    if not run_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search run not found."
        )

    db_status = run_doc.get("status")
    if db_status == "RUNNING":
        try:
            client = ApifyClient(APIFY_API_TOKEN)
            run = client.run(run_id).get()
            apify_status = get_field(run, "status", "UNKNOWN")
            
            if apify_status == "SUCCEEDED":
                dataset_id = get_field(run, "defaultDatasetId") or get_field(run, "default_dataset_id")
                logger.info(f"Poller: Run {run_id} succeeded. Dataset ID: {dataset_id}")
                items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
                logger.info(f"Poller: Iterated {len(items)} items from dataset.")
                groups_list = build_groups_list(items)
                
                search_type = run_doc.get("search_type")
                run_input = run_doc.get("run_input", {})
                if search_type == "easyapi":
                    raw_output = build_easyapi_raw_output(items, run_input)
                else:
                    raw_output = build_grouped_raw_output(items, run_input)
                    
                db.fb_groups_extractor.update_one(
                    {"_id": run_id},
                    {
                         "$set": {
                             "status": "SUCCEEDED",
                             "total_groups": len(items),
                             "groups": groups_list,
                             "raw_output": raw_output
                         }
                    }
                )
                run_doc = db.fb_groups_extractor.find_one({"_id": run_id})
                
            elif apify_status in ("FAILED", "ABORTED", "TIMED-OUT"):
                db.fb_groups_extractor.update_one(
                    {"_id": run_id},
                    {
                        "$set": {
                            "status": "FAILED" if apify_status != "ABORTED" else "ABORTED"
                        }
                    }
                )
                run_doc = db.fb_groups_extractor.find_one({"_id": run_id})
                
        except Exception as e:
            logger.error(f"Failed to poll status from Apify: {e}")
            
    return SearchResponse(
        status=run_doc.get("status", "UNKNOWN"),
        total_groups=run_doc.get("total_groups", 0),
        groups=run_doc.get("groups", []),
        raw_output=run_doc.get("raw_output", {}),
        run_id=run_doc.get("run_id", ""),
        search_type=run_doc.get("search_type", ""),
        search_input=run_doc.get("search_input", ""),
        max_items=run_doc.get("max_items", 20)
    )

@app.post("/api/search/stop/{run_id}")
def run_search_stop(run_id: str):
    if not APIFY_API_TOKEN or APIFY_API_TOKEN.startswith("your_"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Apify API token not configured."
        )
        
    try:
        client = ApifyClient(APIFY_API_TOKEN)
        client.run(run_id).abort()
        
        if db is not None:
            db.fb_groups_extractor.update_one(
                {"_id": run_id},
                {
                    "$set": {
                        "status": "ABORTED"
                    }
                }
            )
        return {"status": "ABORTED"}
    except Exception as e:
        logger.error(f"Failed to abort run {run_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to abort run on Apify: {str(e)}"
        )

@app.get("/api/search/latest", response_model=SearchResponse)
def get_latest_search():
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection is unavailable."
        )
    
    latest_run = db.fb_groups_extractor.find_one(sort=[("timestamp", -1)])
    if not latest_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No runs found."
        )

    db_status = latest_run.get("status")
    run_id = latest_run.get("run_id")
    
    if db_status == "RUNNING" and run_id:
        try:
            client = ApifyClient(APIFY_API_TOKEN)
            run = client.run(run_id).get()
            apify_status = get_field(run, "status", "UNKNOWN")
            
            if apify_status == "SUCCEEDED":
                dataset_id = get_field(run, "defaultDatasetId") or get_field(run, "default_dataset_id")
                logger.info(f"Latest: Run {run_id} succeeded. Dataset ID: {dataset_id}")
                items = list(client.dataset(dataset_id).iterate_items()) if dataset_id else []
                logger.info(f"Latest: Iterated {len(items)} items from dataset.")
                groups_list = build_groups_list(items)
                
                search_type = latest_run.get("search_type")
                run_input = latest_run.get("run_input", {})
                if search_type == "easyapi":
                    raw_output = build_easyapi_raw_output(items, run_input)
                else:
                    raw_output = build_grouped_raw_output(items, run_input)
                    
                db.fb_groups_extractor.update_one(
                    {"_id": run_id},
                    {
                        "$set": {
                            "status": "SUCCEEDED",
                            "total_groups": len(items),
                            "groups": groups_list,
                            "raw_output": raw_output
                        }
                    }
                )
                latest_run = db.fb_groups_extractor.find_one({"_id": run_id})
            elif apify_status in ("FAILED", "ABORTED", "TIMED-OUT"):
                db.fb_groups_extractor.update_one(
                    {"_id": run_id},
                    {
                        "$set": {
                            "status": "FAILED" if apify_status != "ABORTED" else "ABORTED"
                        }
                    }
                )
                latest_run = db.fb_groups_extractor.find_one({"_id": run_id})
        except Exception as e:
            logger.error(f"Failed to poll latest run status from Apify: {e}")

    return SearchResponse(
        status=latest_run.get("status", "UNKNOWN"),
        total_groups=latest_run.get("total_groups", 0),
        groups=latest_run.get("groups", []),
        raw_output=latest_run.get("raw_output", {}),
        run_id=latest_run.get("run_id", ""),
        search_type=latest_run.get("search_type", ""),
        search_input=latest_run.get("search_input", ""),
        max_items=latest_run.get("max_items", 20)
    )