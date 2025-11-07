
import argparse
import asyncio
import json
from tesseract_async_client import TesseractAsyncClient

HARDCODED_FILE_PATH = None

async def run(file_path: str, wait: bool, poll_interval: float, timeout: float, base_url: str) -> None:
    async with TesseractAsyncClient(base_url=base_url) as client:
        upload_resp = await client.upload(file_path)
        print(json.dumps(upload_resp, ensure_ascii=False))
        file_id = upload_resp.get("id")
        if wait and file_id:
            result = await client.wait_for_result(file_id, poll_interval=poll_interval, timeout=timeout)
            print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="Path to PDF file to upload")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--base-url", default="https://dev-ocr.fortebank.com/v2")
    args = parser.parse_args()
    file_path = args.file if args.file else HARDCODED_FILE_PATH
    if not file_path:
        raise SystemExit("No file provided. Set HARDCODED_FILE_PATH or pass a file argument.")
    wait_flag = True if not args.file else args.wait
    asyncio.run(
        run(
            file_path=file_path,
            wait=wait_flag,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            base_url=args.base_url,
        )
    )


if __name__ == "__main__":
    main()

