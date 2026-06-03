# WeChat Layout Workbench Notes

## Core Flow

- Keep Feishu import structural fidelity first: tables, quotes, ordered-list continuity, image grids, and video placeholders should not regress.
- For WeChat copy, do not use Feishu internal media URLs as final image sources. WeChat may reject them because they are not normal public image URLs.
- For large Feishu documents, avoid putting every local image into clipboard HTML as a base64 data URL. Use public R2 image URLs when available, and keep base64 only as a fallback.

## R2 Image Copy

- The workbench reads R2 config from environment variables:
  - `R2_BUCKET_NAME`
  - `R2_ACCESS_KEY_ID`
  - `R2_SECRET_ACCESS_KEY`
  - `R2_ENDPOINT`
  - `NEXT_PUBLIC_R2_PUBLIC_URL`
- Local development also falls back to:
  - `/Users/shitengda/Downloads/docker/n8n/vibeAgent/finalAgent/video-agent-pro/.env.local`
- Imported Feishu images stay local for preview via `data-local-src`.
- During conversion, Feishu local images under `output/_feishu_media/` are uploaded to R2 and annotated with `data-r2-src`.
- The front-end copy path should prefer `data-r2-src`; if unavailable, it may fall back to the old data URL copy path.
- Temporary R2 image access should last 24 hours. Configure an R2 lifecycle rule to delete the `temp/wechat-layout/` prefix after 1 day.

## Verification

- Run `python3 -m pytest tests` before pushing.
- For image-heavy Feishu docs, verify the generated HTML has matching `data-local-src` and `data-r2-src` counts and no `data:image/` payloads in the final content HTML.
