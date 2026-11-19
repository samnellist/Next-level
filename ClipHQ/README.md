# Clip HQ

**Turn long streams and videos into ready-to-post vertical Shorts.** Free, runs on your own laptop, no watermarks, no paid APIs.

Made for clipping GTA 6 streamers (facecam on top, gameplay below), and it also works for talking, IRL and podcast videos.

---

## 1. Install (one time, about 10–20 minutes)

1. Download this folder to your laptop (GitHub → **Code → Download ZIP**, then right-click the ZIP → **Extract All**).
   Put it somewhere simple, like `C:\ClipHQ` or your Documents folder.
2. Open the `ClipHQ` folder and double-click **`Install Clip HQ.bat`**.
   - If Windows shows "Windows protected your PC", click **More info → Run anyway**.
   - The installer checks your processor (Intel, or ARM/Snapdragon) and picks the right versions, then installs:
     Python 3.12, FFmpeg (the video engine), the speech model, face detector, on-screen text reader and caption fonts.
   - Nothing needs admin rights, and nothing is installed outside the `ClipHQ` folder except Python itself.
3. When it says **All done**, you'll have a **Clip HQ** icon on your desktop.

> **Snapdragon / ARM Surface?** That's fine. FFmpeg runs natively on ARM. The speech-to-text engine
> doesn't have an ARM version yet, so Windows runs it with its built-in emulation (a bit slower, works the same).

## 2. Start it

Double-click **Clip HQ** on your desktop (or `Start Clip HQ.bat`).
A black window opens (**keep it open** while you use the app) and your browser opens at **http://localhost:8000**.

The first time, Windows may ask whether Python can use the network: tick **Private networks** and click **Allow**.
Your phone needs this.

To stop Clip HQ, close the black window.

## 3. Make clips from a video

1. Go to **Process**.
2. Click **Browse…** and pick your video (any format: mp4, mkv, mov, iPhone recordings, 3-hour streams…),
   or pick a folder to queue every video in it.
3. **Type of video:** choose **GTA 6 streamer** for GTA streams (or *Talking / IRL* for podcasts and chats).
4. **Campaign:** choose one if this is for a paid campaign (see section 8).
5. Click **Start processing**. You'll see the progress (Transcribing 40%, Reading on-screen text…).
   You can queue as many videos as you like; they're done one after another.
6. You get a notification when the clips are ready. Open **Review**.

**How long does it take?** On a 4-core laptop, roughly a quarter to a third of the video's length
(a 1-hour stream ≈ 15–20 minutes). Long quiet stretches (just driving around) are skipped to save time.

### Drop folder (automatic)
Anything you put in `ClipHQ\input\drop` (for example campaign footage you downloaded from the campaign's
own content folder) is processed automatically. Tick *"Use these settings for the drop folder too"* on the
Process page to choose its type and campaign.

## 4. Review and post

**Review** shows every clip, **best first**, with a **score out of 100** and a one-line reason
(e.g. *"Crash: a strong reaction + an explosion / crash sound ("no way")"*).

Click a clip to:
- change the **hook text** at the top, and add **more text** that appears later in the clip
- **trim** the start/end (±1 second buttons)
- change the **layout**: facecam-on-top, face-tracked, wide, blurred background, follow-the-action
- change the **caption style**, or press **🎲 New style** for a fresh random look
- draw the **facecam box** yourself if the automatic one is off
- edit the **title and description**, and tick the campaign **checklist**
- **✓ Approve** or **Delete**

Approved clips go to the `approved` folder and the **Exports** page, with **Copy** buttons for the title and description and a **Download** button.

Every clip is 1080×1920, H.264 MP4, 30fps, with sound levelled to -14 LUFS (YouTube's loudness) and **no watermark**.

## 5. Use it on your iPhone

Your laptop and iPhone must be on the **same Wi-Fi**.

1. When Clip HQ starts, the black window shows a line like
   `On your iPhone (same Wi-Fi): https://192.168.1.23:8443/m`
2. Type that into Safari on your iPhone. You'll see a warning the first time: tap **Show Details → visit this website**.
3. **One-time setup for "Save to Photos"** (Apple only allows it on trusted secure pages):
   1. On the phone page, tap **"Tap here to download the Clip HQ certificate"** → **Allow**.
   2. iPhone **Settings → General → VPN & Device Management** → *Clip HQ Local CA* → **Install**.
   3. **Settings → General → About → Certificate Trust Settings** → switch on *Clip HQ Local CA*.
   4. Reload the page. Tap the Share icon → **Add to Home Screen** so it feels like an app.

   This certificate was made on your laptop and only works for Clip HQ.

On the phone you can:
- **Upload** iPhone screen recordings straight to the laptop (no cable). They're processed automatically.
- Watch, **approve** or **delete** clips, and **copy** the title or description.
- **📲 Save to Photos:** tap once (it prepares the video), tap again, then choose **Save Video**. It goes into your camera roll.
- See a banner when new clips are ready.

## 6. Record a stream (hands-free)

Go to **Record**:
1. **Record:** *Whole screen*, or *One window* (pick your browser window playing the stream; keep it visible, not minimised).
2. **Sound:** *What I hear* records the stream's sound (whatever plays through your speakers/headphones).
3. **Auto-stop after:** e.g. 180 minutes, so you can start it and walk away.
4. Press **● Record**.

While recording:
- Your laptop **won't sleep or turn the screen off**.
- The recording is saved in **20-minute chunks**. Each finished chunk goes to Process straight away,
  so clips appear **while it's still recording**, and you get a notification on the laptop and phone.
- Press **■ Stop** (or let auto-stop do it). The last chunk is processed too.

Tip: turn on Windows **Do not disturb** so pop-ups don't end up in the recording.

## 7. Scout mode (find moments fast at 2x speed)

If you watched/recorded a stream at **2x speed** to save time:
1. On **Process**, tick **Scout mode** and set the speed (e.g. 2).
2. Clip HQ slows the sound back down so speech recognition and audio analysis still work, and gives you
   a list of the best moments **in the original video's time**, e.g. `12:40–13:05  police chase crash`.
3. Go back to those times at normal speed and record just those bits for the final clips.

## 8. Campaigns

**Campaigns** → fill in name, required hashtags, tags, pay rate, who must be the main focus, and the rules
(one per line). Example:

| Field | Example |
|---|---|
| Name | Lacy |
| Hashtags | #Lacy #shorts |
| Rules | #Lacy in caption · Lacy must be the main focus · No logos |

Choose the campaign when you process a video (or later in the clip editor). Each clip then gets a title
under 70 characters with an emoji and the hashtags, a description, and a **checklist** of the rules to tick before posting.

## 9. Watch channels for new uploads

**Watcher** → paste a channel link or @handle (e.g. `@momentsdailyuk` or `https://www.youtube.com/@name`) → **Add**.

Clip HQ checks each channel's public YouTube feed **every 10 minutes** (no API key). When there's a new video
you get a **Windows notification**, and it appears in the list with the title, thumbnail, link and time posted.
It remembers what it has shown you, so you're never told about the same video twice.

> Clip HQ never downloads videos from YouTube or any other site; that's against their rules and could get
> your channel in trouble. Use campaign footage folders or your own screen recordings.

## 10. GTA 6 mode, and teaching it

The **GTA 6 streamer** type combines what the streamer does with what happens in the game:
- **Streamer:** screaming, laughing, "no way", "let's go", sudden changes in pace
- **Game sound:** explosions/crashes, gunfire bursts, police sirens, sudden music changes
- **Action:** big motion spikes, camera shake, quick cuts
- **On-screen text:** WASTED / BUSTED / MISSION PASSED / FAILED, and the wanted stars going up
- Bonus points when the streamer reacts right after something happens in the game.
- Fails and crashes start 2–4 seconds before the impact, so the payoff lands.

GTA 6's on-screen words and layout may differ from older GTA games. In **Settings → GTA 6 mode** you can edit
the phrases it looks for and the screen areas it reads (as `x,y,w,h` fractions: `0.7,0,0.3,0.2` = top-right corner).

**Teach it:** on Process, a finished video has **⭐ Mark a good moment**. Type a time like `12:40`.
In the clip editor, **⭐ Great moment** does the same, and every clip you **approve** counts too.
Clip HQ learns which signals your favourite moments share and any on-screen words that keep appearing.
See (and reset) what it has learned at the bottom of Settings.

Other options: **Blur the HUD/minimap**, **skip quiet driving** (on by default), and blurring chat boxes or pop-ups
(Settings → *Blur stream chat / pop-ups*).

## 11. Smart mode (optional)

If you have your own **Claude API key**, paste it in **Settings → Smart mode** and press **Test**.
Claude then re-ranks the moments and writes hooks and titles. Only the **transcript text** is sent, never the video.
It costs a few cents per video on your Anthropic account. Without a key, everything still works for free.

## Folders

| Folder | What's in it |
|---|---|
| `input` | your videos. `input\drop` = auto-process, `input\recordings` = screen recordings, `input\uploads` = from your phone |
| `clips` | every clip made, for review |
| `approved` | approved clips + a `.txt` with the title, description and checklist |
| `data` | settings, database, temporary files (safe to delete `data\work` to free space) |

## Fixing common problems

| Problem | Fix |
|---|---|
| Installer closes or shows red text | Run `Install Clip HQ.bat` again: it skips what's already done. Check you're online. |
| "Windows protected your PC" | Click **More info → Run anyway**. |
| Browser says "can't reach this page" | The black Clip HQ window must be open. Start it from the desktop icon. |
| Phone can't open the page | Same Wi-Fi as the laptop? Windows: **Settings → Network → Wi-Fi → your network → Private**. If you clicked "Cancel" on the firewall question: Windows Security → Firewall → *Allow an app* → tick Python (Private). |
| "Save to Photos" says to use Download | Do the one-time certificate setup in section 5 and open the **https://…:8443** address. |
| Recording has no sound | Something must be playing through your speakers when you start. Or choose *Sound: An audio device* and pick "Stereo Mix". |
| Recording shows a black window | Choose *Whole screen* instead, and don't minimise the window you're recording. |
| Processing is slow | Settings → Speech model → **Fast (base)**. Leave "skip quiet driving" on. Close other heavy apps. |
| Captions are cut off or wrong words | Edit the clip and change the caption style, or set Speech model to **Accurate (small)**. |
| Wrong part of the screen on top in stacked layout | Edit the clip → *Facecam box* → drag around the streamer's camera → Save & re-render. |
| GTA moments missed | Mark a few good moments (section 10) and check the OCR phrases match what the game shows. |
| Ran out of disk space | Delete old files in `input\recordings`, `clips` and `data\work`. |
| Something else | Close the black window and start Clip HQ again. Errors show in red on the Process page. |

## How it finds the best moments (for the curious)

1. **Transcribe** with faster-whisper (word-by-word timestamps), 10 minutes at a time so long streams don't run out of memory.
2. **Score every second** from audio (loudness spikes, explosions, gunfire, sirens, music changes), video (motion
   spikes, cuts, shake), the transcript (reactions, laughter, questions and answers, stories) and on-screen text.
3. **Build each clip** around a peak: start at the setup line or just before the impact, skip "um" and silence,
   end after the payoff at the end of a sentence with a pause (so it loops nicely), 10–30 seconds, no overlaps.
4. **Frame it:** finds the facecam box and faces, follows the speaker or the action with smooth camera moves,
   and burns in word-by-word captions above YouTube's buttons (out of the bottom 25%).
