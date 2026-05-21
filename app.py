import re
import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from curl_cffi.requests import AsyncSession

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

api = FastAPI(title="UL Sniper (Omni-Extractor Edition)")

def format_duration(raw_dur):
    if not raw_dur: return "Unknown"
    raw_dur = str(raw_dur).strip().upper()
    
    # 💀 THE ISO 8601 HUNTER (Catches PT19M57S, P0DT0H13M41S, etc.)
    match = re.search(r'P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', raw_dur)
    if match:
        d = int(match.group(1)) if match.group(1) else 0
        h = int(match.group(2)) if match.group(2) else 0
        m = int(match.group(3)) if match.group(3) else 0
        s = int(match.group(4)) if match.group(4) else 0
        
        total_seconds = (d * 86400) + (h * 3600) + (m * 60) + s
        
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        
    # Raw seconds fallback (if they just send "2125")
    if raw_dur.replace('.', '').isdigit():
        total_seconds = int(float(raw_dur))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        
    return raw_dur

@api.get("/api/health")
async def health_check():
    return {"status": "200 OK", "engine": "Omni-Extractor Online 🔥"}

@api.get("/api/download")
async def extract_media(url: str):
    logger.info(f"🎯 Ripping: {url}")
    try:
        # Ghost Mode: Let curl_cffi handle ALL headers mathematically perfectly
        async with AsyncSession(impersonate="chrome116") as session:
            response = await session.get(url, timeout=15)
            raw_html = response.text
            clean_html = raw_html.replace('\\/', '/')
            
            # ==========================================
            # 1. UNIVERSAL TITLE EXTRACTOR
            # ==========================================
            title = "Unknown Title"
            title_match = re.search(r'<meta[\s\S]+?(?:property|name)=["\'](?:og:title|twitter:title)["\'][\s\S]+?content=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1)
            else:
                title_match = re.search(r'<title[^>]*>([\s\S]*?)</title>', raw_html, re.IGNORECASE)
                if title_match: title = title_match.group(1)
            
            # Clean up common tube site branding from titles for a premium look
            title = re.sub(r' - (XVIDEOS\.COM|XNXX\.COM|XXXBP|SexVid\.xxx)$', '', title, flags=re.IGNORECASE)
            title = title.replace(" | xHamster", "").replace(" | PussySpace", "").strip()
            
            # ==========================================
            # 2. UNIVERSAL THUMBNAIL EXTRACTOR
            # ==========================================
            thumbnail = None
            thumb_match = re.search(r'<meta[\s\S]+?(?:property|name)=["\'](?:og:image|twitter:image)["\'][\s\S]+?content=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
            if thumb_match: thumbnail = thumb_match.group(1)
            
            # ==========================================
            # 3. UNIVERSAL DURATION EXTRACTOR
            # ==========================================
            duration = "Unknown"
            # Attack A: Hidden in JSON (xHamster)
            dur_match = re.search(r'"duration"\s*:\s*(\d+)', raw_html)
            
            # Attack B: Standard Meta Tags
            if not dur_match:
                dur_match = re.search(r'<meta[\s\S]+?(?:property|itemprop)=["\'](?:video:duration|og:duration|duration|og:video:duration)["\'][\s\S]+?content=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
            if dur_match: 
                duration = format_duration(dur_match.group(1))

            # ==========================================
            # 4. OMNI-STREAM EXTRACTOR (Cascading Attack)
            # ==========================================
            stream_url = None
            
            # Attack Vector 1: xHamster Preload
            preload_match = re.search(r'<link[^>]+?href=["\'](https?://[^"\']+\.m3u8[^"\']*)["\'][^>]*?as=["\']fetch["\']', raw_html, re.IGNORECASE)
            if preload_match:
                stream_url = preload_match.group(1)

            # Attack Vector 2: XVideos/XNXX JS Player
            if not stream_url:
                x_match = re.search(r"html5player\.setVideoHLS\(['\"](https?://[^'\"]+)['\"]\)", clean_html)
                if not x_match:
                    x_match = re.search(r"html5player\.setVideoUrlHigh\(['\"](https?://[^'\"]+)['\"]\)", clean_html)
                if x_match: stream_url = x_match.group(1)
            
            # Attack Vector 3: Universal Naked M3U8
            if not stream_url:
                m3u8_links = re.findall(r'(https?://[^\s"\'<>\[\]()]+?\.m3u8[^\s"\'<>\[\]()]*)', clean_html)
                if m3u8_links: stream_url = m3u8_links[0]
                
            # Attack Vector 4: Universal Naked MP4 (Filtered to avoid thumbnails)
            if not stream_url:
                mp4_links = re.findall(r'(https?://[^\s"\'<>\[\]()]+?\.mp4[^\s"\'<>\[\]()]*)', clean_html)
                for link in mp4_links:
                    lower_link = link.lower()
                    if not any(bad in lower_link for bad in ['preview', 'thumb', 'poster', '.jpg', '.png', '.webp']):
                        stream_url = link
                        break

            # Attack Vector 5: Native Meta/Link Tags (PussySpace, XXXBP, SexVid)
            if not stream_url:
                og_vid = re.search(r'<meta[\s\S]+?(?:property|name)=["\'](?:og:video:url|og:video|twitter:player)["\'][\s\S]+?content=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
                if og_vid: stream_url = og_vid.group(1)

            if not stream_url:
                vid_src = re.search(r'<link[\s\S]+?rel=["\']video_src["\'][\s\S]+?href=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
                if vid_src: stream_url = vid_src.group(1)

            # Attack Vector 6: Standard <source> tags (WP-Tube themes like fry99)
            if not stream_url:
                source_tag = re.search(r'<source[\s\S]+?src=["\']([^"\']+)["\']', raw_html, re.IGNORECASE)
                if source_tag: stream_url = source_tag.group(1)

            if not stream_url:
                return {
                    "error": "Media stream not found. Omni-Extractor exhausted.",
                    "diagnostics": {
                        "downloaded_page_title": title,
                        "html_snippet": raw_html[:300] 
                    }
                }
                
            return {
                "title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "stream_url": stream_url
            }
            
    except Exception as e:
        return {"error": f"Extraction failed: {str(e)}"}

@api.get("/api/source", response_class=HTMLResponse)
async def get_raw_source(url: str):
    try:
        async with AsyncSession(impersonate="chrome116") as session:
            response = await session.get(url, timeout=15)
            return response.text
    except Exception as e: return f"Error: {str(e)}"

if __name__ == "__main__":
    uvicorn.run(api, host="0.0.0.0", port=8000)
