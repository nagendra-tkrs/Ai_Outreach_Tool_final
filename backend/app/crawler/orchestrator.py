import os
import asyncio
from datetime import datetime, timezone
from urllib.parse import urljoin
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id
from app.crawler.fetcher import fetch_page, FetchError
from app.crawler.content_extractor import extract_content
from app.crawler.link_extractor import extract_links, extract_links_with_metadata, KNOWN_LEADERSHIP_PATHS
from app.crawler.page_classifier import classify_page, get_page_priority
from app.crawler.url_utils import normalize_url, extract_domain, is_same_domain
from app.crawler.sitemap_parser import fetch_sitemap
from app.crawler.robots_handler import is_allowed
from app.crawler.content_validator import validate_crawled_page

def get_config():
    return {
        'maxPagesPerCompany': int(os.getenv('MAX_PAGES_PER_COMPANY', 25)),
        'maxCrawlDepth': int(os.getenv('MAX_CRAWL_DEPTH', 2)),
        'requestTimeout': int(os.getenv('CRAWLER_TIMEOUT_MS', 10000)),
        'concurrency': int(os.getenv('CRAWL_CONCURRENCY', 3))
    }

async def crawl_company(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    config = get_config()
    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company.get("website"):
        raise HTTPException(status_code=400, detail="Company has no website")

    website = company["website"]
    base_domain = extract_domain(website)
    normalized_base = normalize_url(website)

    existing_job = await db.researchjobs.find_one({
        "companyId": cid,
        "type": "website_crawl",
        "status": "running"
    })
    if existing_job:
        raise HTTPException(status_code=409, detail="Crawl already in progress")

    now = datetime.now(timezone.utc)
    await db.companies.update_one({"_id": cid}, {"$set": {"crawlStatus": "crawling", "updatedAt": now}})

    job_doc = {
        "companyId": cid,
        "type": "website_crawl",
        "status": "running",
        "startedAt": now,
        "createdAt": now,
        "updatedAt": now
    }
    insert_res = await db.researchjobs.insert_one(job_doc)
    job_id = insert_res.inserted_id

    print(f"[CRAWLER] Starting crawl for: \"{company.get('companyName')}\" ({website})")

    try:
        visited = set()
        queue = [{"url": normalized_base, "depth": 0, "priority": 100}]
        discovered_urls = {normalized_base}
        pages_crawled = 0
        pages_failed = 0
        pages_blocked = 0

        # Seed paths (known generic probe candidates)
        seed_paths = list(dict.fromkeys([
            '/about', '/about-us', '/team', '/our-team', '/leadership',
            '/leadership-team', '/management', '/management-team', '/board',
            '/board-of-directors', '/directors', '/key-management', '/our-people',
            '/governance', '/corporate-governance', '/people', '/contact', '/contact-us',
            *KNOWN_LEADERSHIP_PATHS
        ]))
        for path in seed_paths:
            try:
                seed_url = normalize_url(urljoin(normalized_base, path))
                if seed_url and seed_url not in discovered_urls:
                    discovered_urls.add(seed_url)
                    queue.append({"url": seed_url, "depth": 1, "priority": get_page_priority(seed_url)})
            except Exception:
                pass

        # Discover from sitemap
        try:
            sitemap_urls = await fetch_sitemap(website)
            for s_url in sitemap_urls:
                n_url = normalize_url(s_url)
                if n_url and is_same_domain(n_url, base_domain) and n_url not in discovered_urls:
                    discovered_urls.add(n_url)
                    queue.append({"url": n_url, "depth": 1, "priority": get_page_priority(n_url)})
        except Exception:
            pass

        # BFS Crawl
        while queue and pages_crawled < config['maxPagesPerCompany']:
            queue.sort(key=lambda x: (-(x.get('priority', 0)), x.get('depth', 0)))

            batch = []
            while queue and len(batch) < config['concurrency']:
                item = queue.pop(0)
                if item['url'] in visited:
                    continue
                if item['depth'] > config['maxCrawlDepth']:
                    continue
                if pages_crawled >= config['maxPagesPerCompany']:
                    break
                batch.append(item)

            if not batch:
                break

            async def process_item(item):
                nonlocal pages_crawled, pages_failed, pages_blocked
                visited.add(item['url'])
                item_now = datetime.now(timezone.utc)

                # 1. Robots.txt check
                try:
                    allowed = await is_allowed(item['url'])
                    if not allowed:
                        pages_blocked += 1
                        print(f"[CRAWLER] Company: {company.get('companyName')} | URL: {item['url']} | Crawl Status: ROBOTS_DISALLOWED")
                        await db.crawledpages.update_one(
                            {"companyId": cid, "normalizedUrl": item['url']},
                            {"$set": {
                                "companyId": cid,
                                "url": item['url'],
                                "normalizedUrl": item['url'],
                                "statusCode": 403,
                                "depth": item['depth'],
                                "pageType": classify_page(item['url']),
                                "crawlStatus": "robots_disallowed",
                                "contentAvailable": False,
                                "contentQuality": "error",
                                "error": "Disallowed by robots.txt",
                                "errorReason": "Disallowed by robots.txt",
                                "crawledAt": item_now,
                                "updatedAt": item_now
                            }},
                            upsert=True
                        )
                        return None
                except Exception as e:
                    print(f"[CRAWLER] Robots.txt check warning: {e}")

                # 2. Fetch page
                try:
                    response = await fetch_page(item['url'], {
                        "timeout": config['requestTimeout'],
                        "maxRetries": 2
                    })
                except FetchError as fetch_err:
                    status_code = fetch_err.statusCode or 0
                    crawl_status = fetch_err.crawlStatus or (
                        'blocked' if status_code == 403 else (
                            'rate_limited' if status_code == 429 else (
                                'not_found' if status_code == 404 else 'failed'
                            )
                        )
                    )
                    is_blocked = crawl_status in ('blocked', 'rate_limited') or status_code in (403, 429)

                    if is_blocked:
                        pages_blocked += 1
                    else:
                        pages_failed += 1

                    print(f"[CRAWLER] Company: {company.get('companyName')} | URL: {item['url']} | HTTP Status: {status_code} | Crawl Status: {crawl_status.upper()}")

                    await db.crawledpages.update_one(
                        {"companyId": cid, "normalizedUrl": item['url']},
                        {"$set": {
                            "companyId": cid,
                            "url": fetch_err.finalUrl or item['url'],
                            "finalUrl": fetch_err.finalUrl or item['url'],
                            "normalizedUrl": item['url'],
                            "statusCode": status_code,
                            "contentType": fetch_err.contentType or '',
                            "depth": item['depth'],
                            "pageType": classify_page(item['url']),
                            "crawlStatus": crawl_status,
                            "contentAvailable": False,
                            "contentQuality": "error",
                            "error": str(fetch_err),
                            "errorReason": fetch_err.errorReason or str(fetch_err),
                            "isChallengePage": bool(fetch_err.isChallengePage or crawl_status == 'blocked'),
                            "crawledAt": item_now,
                            "updatedAt": item_now
                        }},
                        upsert=True
                    )
                    return None

                # 3. Extract content & Validate
                extracted = extract_content(response.get('body', ''), response.get('finalUrl') or item['url'])
                validation = validate_crawled_page({
                    'url': item['url'],
                    'finalUrl': response.get('finalUrl'),
                    'statusCode': response.get('statusCode', 200),
                    'contentType': response.get('contentType', ''),
                    'body': response.get('body', ''),
                    'extracted': extracted,
                    'baseDomain': base_domain
                })

                # 4. Handle invalid or challenge page
                if not validation['isValid']:
                    if validation['crawlStatus'] == 'blocked':
                        pages_blocked += 1
                    else:
                        pages_failed += 1

                    print(f"[CRAWLER] Company: {company.get('companyName')} | URL: {item['url']} | Crawl Status: {validation['crawlStatus'].upper()}")

                    await db.crawledpages.update_one(
                        {"companyId": cid, "normalizedUrl": item['url']},
                        {"$set": {
                            "companyId": cid,
                            "url": response.get('finalUrl') or item['url'],
                            "finalUrl": response.get('finalUrl') or item['url'],
                            "normalizedUrl": item['url'],
                            "title": extracted.get('title', ''),
                            "metaDescription": extracted.get('metaDescription', ''),
                            "headings": extracted.get('headings', []),
                            "content": '',
                            "statusCode": response.get('statusCode', 0),
                            "contentType": response.get('contentType', ''),
                            "contentLength": len(response.get('body') or ''),
                            "depth": item['depth'],
                            "pageType": classify_page(item['url'], extracted.get('title', ''), ''),
                            "wordCount": extracted.get('wordCount', 0),
                            "crawlStatus": validation['crawlStatus'],
                            "contentAvailable": False,
                            "contentQuality": validation['contentQuality'],
                            "error": validation['errorReason'],
                            "errorReason": validation['errorReason'],
                            "isChallengePage": validation.get('isChallengePage', False),
                            "crawledAt": item_now,
                            "updatedAt": item_now
                        }},
                        upsert=True
                    )
                    return None

                # 5. Save Valid Crawled Page
                page_type = classify_page(response.get('finalUrl') or item['url'], extracted.get('title', ''), extracted.get('content', ''))

                await db.crawledpages.update_one(
                    {"companyId": cid, "normalizedUrl": item['url']},
                    {"$set": {
                        "companyId": cid,
                        "url": response.get('finalUrl') or item['url'],
                        "finalUrl": response.get('finalUrl') or item['url'],
                        "normalizedUrl": item['url'],
                        "title": extracted.get('title', ''),
                        "metaDescription": extracted.get('metaDescription', ''),
                        "headings": extracted.get('headings', []),
                        "content": extracted.get('content', ''),
                        "html": (response.get('body') or '')[:200000],
                        "statusCode": response.get('statusCode', 200),
                        "contentType": response.get('contentType', ''),
                        "contentLength": len(response.get('body') or ''),
                        "depth": item['depth'],
                        "pageType": page_type,
                        "wordCount": extracted.get('wordCount', 0),
                        "crawlStatus": "completed",
                        "contentAvailable": True,
                        "contentQuality": "valid",
                        "error": "",
                        "errorReason": "",
                        "isChallengePage": False,
                        "crawledAt": item_now,
                        "updatedAt": item_now
                    }},
                    upsert=True
                )

                pages_crawled += 1

                # Extract links for next depth
                if item['depth'] < config['maxCrawlDepth']:
                    link_metas = extract_links_with_metadata(response.get('body', ''), response.get('finalUrl') or item['url'])
                    for l_meta in link_metas:
                        link = l_meta['url']
                        if link not in discovered_urls and len(discovered_urls) < config['maxPagesPerCompany'] * 2:
                            discovered_urls.add(link)
                            queue.append({
                                "url": link,
                                "depth": item['depth'] + 1,
                                "priority": l_meta.get('priority', get_page_priority(link))
                            })

                return True

            await asyncio.gather(*(process_item(item) for item in batch))
            await asyncio.sleep(0.15)

        # Final status
        final_company_crawl_status = 'completed'
        if pages_crawled == 0:
            final_company_crawl_status = 'blocked' if pages_blocked > 0 else 'failed'

        finish_now = datetime.now(timezone.utc)
        job_status = 'completed' if pages_crawled > 0 else 'failed'
        job_error = ''
        if pages_crawled == 0:
            job_error = 'Website access blocked by bot protection / access controls' if pages_blocked > 0 else 'Crawl completed with 0 accessible pages'

        await db.researchjobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": job_status,
                "completedAt": finish_now,
                "pagesDiscovered": len(discovered_urls),
                "pagesCrawled": pages_crawled,
                "pagesFailed": pages_failed,
                "pagesBlocked": pages_blocked,
                "error": job_error,
                "updatedAt": finish_now
            }}
        )

        await db.companies.update_one(
            {"_id": cid},
            {"$set": {
                "crawlStatus": final_company_crawl_status,
                "lastCrawlJobId": job_id,
                "updatedAt": finish_now
            }}
        )

        print(f"[CRAWLER] Finished crawl for \"{company.get('companyName')}\": {pages_crawled} crawled, {pages_blocked} blocked, {pages_failed} failed, status: {final_company_crawl_status}")

        return {
            "jobId": str(job_id),
            "status": job_status,
            "crawlStatus": final_company_crawl_status,
            "pagesDiscovered": len(discovered_urls),
            "pagesCrawled": pages_crawled,
            "pagesFailed": pages_failed,
            "pagesBlocked": pages_blocked
        }
    except Exception as err:
        finish_now = datetime.now(timezone.utc)
        await db.researchjobs.update_one(
            {"_id": job_id},
            {"$set": {
                "status": "failed",
                "error": str(err),
                "completedAt": finish_now,
                "updatedAt": finish_now
            }}
        )
        await db.companies.update_one(
            {"_id": cid},
            {"$set": {
                "crawlStatus": "failed",
                "updatedAt": finish_now
            }}
        )
        print(f"[CRAWLER] Fatal crawl error: {err}")
        raise err
