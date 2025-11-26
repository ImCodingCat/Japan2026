import requests
import json
import base64
import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv
import instaloader
import concurrent.futures

from datetime import datetime

load_dotenv()

# Load OPEN_ROUTER_API_KEY from .env

def file_to_base64(video_path):
    with open(video_path, "rb") as video_file:
        return base64.b64encode(video_file.read()).decode("utf-8")


def file_extension_to_mime(path: Path):
    extension = path.suffix
    if extension == ".jpg":
        return "jpeg"
    return extension[1:]


api_key = os.getenv("OPEN_ROUTER_API_KEY")


def extract_shortcode_from_url(instagram_url):
    """
    Extract shortcode from Instagram post or reel URL.

    Supports formats:
    - https://www.instagram.com/p/SHORTCODE/
    - https://www.instagram.com/reel/SHORTCODE/
    - https://instagram.com/p/SHORTCODE/
    - https://instagram.com/reel/SHORTCODE/
    """
    pattern = r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)"
    match = re.search(pattern, instagram_url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract shortcode from URL: {instagram_url}")


def _download_instagram_post(shortcode, download_dir):
    download_dir = os.path.join(download_dir, shortcode)
    os.makedirs(download_dir, exist_ok=True)

    # Initialize Instaloader
    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        dirname_pattern=download_dir,
        quiet=True
    )

    # Get post from shortcode
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    # Download the post
    L.download_post(post, target=download_dir)

    # Find the downloaded video file
    download_path = Path(download_dir)
    video_files = list(download_path.glob(f"*.mp4"))

    if video_files:
        return (True, video_files)

    image_extensions = ("*.png", "*.jpg", "*.jpeg")

    image_files = []

    for files in image_extensions:
        image_files.extend(download_path.glob(files))

    return (False, image_files)

def download_instagram_post(shortcode, download_dir="./downloads"):
    for i in range(5):
        try:
            return _download_instagram_post(shortcode, download_dir)
        except Exception as e:
            print(f"Error downloading post: {e}")
            time.sleep(3)
            if i == 4:
                raise e

def summarize_video(video_path):
    """
    Summarize video content using OpenRouter API with Gemini model.

    Args:
        video_path: Path to the video file

    Returns:
        Summary text from the API
    """
    # Encode video to base64
    base64_video = file_to_base64(video_path)
    data_url = f"data:video/mp4;base64,{base64_video}"

    # Prepare API request
    api_key = os.getenv("OPEN_ROUTER_API_KEY")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": """
Analyze this video and extract its core message or content. Focus on:

1. **Text content**: If there's any text, captions, or on-screen writing, transcribe and summarize it
2. **Audio/Speech**: If there's narration, dialogue, or voiceover, summarize what's being said
3. **Main message**: What is the video trying to communicate or teach?

DO NOT describe:
- Background visuals or scenery
- What people are doing physically
- Camera movements or video effects
- Background music (unless it's relevant to the message)

Output format:
- If there's text: Provide the text content
- If there's audio/speech: Summarize the spoken message
- Overall message: What is this video about/trying to convey?

Focus only on the informational or communicative content, not the visual presentation.
""",
                },
                {"type": "video_url", "video_url": {"url": data_url}},
            ],
        }
    ]

    payload = {"model": "google/gemini-2.5-flash-preview-09-2025", "messages": messages}

    response = requests.post(url, headers=headers, json=payload)
    response_text = response.text
    try:
        result = json.loads(response_text)

        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            return result
    except:
        print(response_text)


def summarize_image(images: list[Path]):
    """
    Summarize video content using OpenRouter API with Gemini model.

    Args:
        video_path: Path to the video file

    Returns:
        Summary text from the API
    """
    # Encode video to base64

    base64_images = [
        f"data:image/{file_extension_to_mime(path)};base64,{file_to_base64(path)}"
        for path in images
    ]

    # Prepare API request
    api_key = os.getenv("OPEN_ROUTER_API_KEY")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    content = [
        {
            "type": "text",
            "text": """
Analyze this images and extract its core content or message. Focus on:

1. **Text content**: If there's any text, captions, labels, or writing, transcribe it completely
2. **Infographic data**: If it contains charts, graphs, statistics, or data visualizations, extract the key information
3. **Main message**: What information is this image trying to communicate?

DO NOT describe:
- Background aesthetics or design elements
- Colors, fonts, or styling (unless crucial to understanding)
- General scene descriptions
- Decorative elements

Output format:
- Only output the entire summarization

Focus only on extracting the informational content, not describing how it looks.
""",
        },
    ]

    for image in base64_images:
        content.append({"type": "image_url", "image_url": {"url": image}})

    messages = [{"role": "user", "content": content}]

    payload = {"model": "qwen/qwen3-vl-30b-a3b-instruct", "messages": messages}

    response = requests.post(url, headers=headers, json=payload)
    result = response.json()
    if "choices" in result and len(result["choices"]) > 0:
        return result["choices"][0]["message"]["content"]
    else:
        return result


def summarize_instagram_post(instagram_url, share_text, download_dir="./downloads"):
    """
    Download and summarize an Instagram post or reel from URL.

    Args:
        instagram_url: Instagram post or reel URL
        download_dir: Directory to save downloaded content

    Returns:
        Dictionary containing video path and summary
    """
    print(f"Downloading from: {instagram_url}")

    os.makedirs("summarization", exist_ok=True)

    shortcode = extract_shortcode_from_url(instagram_url)

    if not os.path.exists(f"summarization/{shortcode}.md"):
        # Download the post/reel
        (is_video, files) = download_instagram_post(shortcode, download_dir)

        # Summarize the video
        print(f"Analyzing {"video" if is_video else "image"} content...")

        summary = summarize_video(files[0]) if is_video else summarize_image(files)

        with open(f"summarization/{shortcode}.md", "w", encoding="utf-8") as f:
            share_text = re.sub(r'\\u[0-9a-fA-F]{4}', '', share_text)
            f.write(f"# {share_text}\n\n{summary}")

        print(f"Summarization saved to summarization/{shortcode}.md")
    else:
        print(f"Summarization already exists for {shortcode}")


# Get messages data from Exporting group chat in Instagram where you share interesting reels into it.

if __name__ == "__main__":
    links_list = []

    with open("message_1.json", "r") as f:
        data = json.load(f)
        for message in data["messages"]:
            if "share" in message:
                timestamp_ms = message["timestamp_ms"]
                
                message_date = datetime.fromtimestamp(timestamp_ms / 1000)

                links_list.append({
                    "link": message["share"]["link"],
                    "share_text": message["share"]["share_text"]
                })

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for link in links_list:
            executor.submit(summarize_instagram_post, link["link"], link["share_text"])
