# Recording the PR-Guard demo

Status: **not recorded yet.** There is no video in this repository. The README links here
rather than embedding an empty player or a fabricated "live" clip.

## What the recording must show

The public deployment is a **replay of one genuine local run**, not a live backend. A
recording is honest only if the viewer can see that. Show the banner before anything else.

The capture behind the demo used real npm, Vitest and SQLite, with `FakeLLM`, an in-process
fake GitHub client and `LocalSandboxRunner`. It did **not** use Docker, a GitHub App or a
provider API. Do not record a slide that implies otherwise.

## Before recording

1. Open the live demo and confirm the banner says
   `Demo mode: replaying recorded results from real runs (captured …, commit …)`.
2. Use a clean browser profile or an incognito window with no bookmarks, extensions or
   personal tabs visible.
3. Set the viewport to **1440×900** at 100% zoom. Record at 30 fps, H.264, no audio.
4. Close notifications. Keep the cursor visible and move it deliberately.
5. Rehearse once. The final clip should be **60–120 seconds**, not a raw five-minute take.

## Shot list (about 90 seconds)

| Time | Action | What the viewer should understand |
| --- | --- | --- |
| 0–8 s | Open `/`. Hold on the amber banner. | This is recorded data, with a capture date, commit, fake GitHub and `LocalSandboxRunner` named. |
| 8–20 s | Slow scroll over the four metric cards and the run table. | One run: 1 verified test, 78.57% → 100.00%, 23,972 ms, $0.00 from `FakeLLM`. |
| 20–30 s | Select status `succeeded`, click **Filter**. | URL filters still work without a backend. |
| 30–40 s | Click `acme/prguard-demo`. | The detail page opens; the recorded-run note is visible above the title. |
| 40–58 s | Scroll the metrics, then the verified test. Expand `tests/score.test.ts · normalizeScore`. | The generated Vitest code and the verification result are real persisted artifacts. |
| 58–70 s | Expand **View captured output**. | Sandbox evidence includes the real Vitest coverage table; the environment label is local. |
| 70–80 s | Hover **Open PR unavailable** and the header **Recorded · read only** pill. | Live mutations are disabled with an explanation, not silently broken. |
| 80–90 s | Open `/?status=failed`, then `/runs/missing`. | Empty and 404 states are intentional and honest. |

Do not speed up or edit the numbers. If the capture is regenerated, record again; do not
reuse a clip whose banner shows an older commit.

## Tools

Any of these is fine:

- **OBS Studio** — display capture, 1440×900 output, `x264`, rate control `CRF 23`.
- **Windows Game Bar** — `Win+G`, capture the browser window only.
- **ScreenToGif** — for a short GIF, but prefer MP4 for the README.

Trim the start and end. Keep the banner readable at 720p; 1440×900 downscales cleanly.

## Output and embed location

Save the final file as:

```text
docs/demo/pr-guard-demo.mp4
```

Keep it under **10 MB** if possible. Then open `README.md`, find the `## Live demo` section,
and replace the placeholder comment with:

```markdown
https://github.com/user-attachments/assets/REPLACE-WITH-YOUR-UPLOAD-ID
```

or, if the file is committed:

```markdown
![PR-Guard demo recording](docs/demo/pr-guard-demo.mp4)
```

GitHub renders committed MP4s from the repository page, but a user-attachment URL is
preferred because it avoids adding a large binary to git history. The recording guide link
in the demo banner points back to this file, so keep the filename stable.

## After recording

- [ ] Banner date and commit match the deployed `manifest.json`.
- [ ] The words "FakeLLM", "fake GitHub" and "LocalSandboxRunner" are visible in the clip.
- [ ] No real repository, token, email, local path or provider key appears.
- [ ] The video is labelled as a demo replay in the README, not as a live run.
- [ ] The file is compressed and the README link resolves.

## If a real live run becomes available

A live recording needs a GitHub App installation, a provider key and Docker. Run the same
journey against the live dashboard, then update `dashboard/public/demo-data/manifest.json`
through `scripts/capture_demo_data.py` so the banner names the new capture. Do not mix
frames from the local capture and a live run in one clip.
