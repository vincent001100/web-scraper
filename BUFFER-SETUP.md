# Switch the daily post to Buffer (no more Make.com timer)

**What this does.** Every evening (about 19:17 Lagos) the robot makes *tomorrow's* picture and hands
it to Buffer. Buffer posts it to the Facebook Page and Instagram at exactly **07:00 Lagos**. Make.com
is not needed any more, and GitHub being late no longer matters. At 07:41 a second robot asks Buffer
"did it really go out?" and GitHub shows a **red X and emails you** if not.

**Nothing changes until both the key (step 4) and the update (step 5) are in.** Until then the robot keeps posting the Make.com way.

Words: an **API key** is a password for robots. A **secret** is GitHub's safe box for passwords.
**Never send the key to anyone**: not in chat, not by email. If it leaks, make a new key in Buffer
and the old one stops working at once.

## Steps (about 20 minutes, easiest on a computer)

1. **Make a free Buffer account** at buffer.com (the Free plan: 3 channels, enough for Facebook and Instagram).
2. **Connect Facebook.** In Buffer: *Channels, Connect a channel, Facebook*. You must be an **admin with full control** of the Solvix Page. In Facebook's pop-up keep every switch on and tick the Page.
3. **Connect Instagram.** The account must be **Business or Creator** (in the Instagram app: *Settings, Account type and tools, Switch to professional account*). Then in Buffer: *Connect a channel, Instagram*. Linking Instagram to the Facebook Page is the safest route (it is how Make.com did it). Buffer's help says the link is optional, but we have not tested that.
4. **Make the API key and put it in GitHub.**
   - Buffer: your picture (bottom left), then **API** (or publish.buffer.com/settings/api). *Personal Access, + New Key.* Name it `Solvix robot`, leave the permissions ticked, and **choose 1 year** as the expiry (a 7-day key would stop the robot after a week). *Generate API Key*, then *Copy key*.
   - GitHub: the web-scraper project, *Settings, Secrets and variables, Actions, New repository secret*. Name: `BUFFER_API_KEY`. Paste the key. *Add secret*.
   - Ask Operations to put a reminder in the task list 2 weeks before the key's expiry date.
5. **Tell the Builders "the Buffer key is in".** With your OK they switch on the prepared update (the branch `claude/post-via-buffer`). It is safe at any time: without the key it changes nothing.
6. **Rehearse (nothing is published).** GitHub: *Actions, Buffer tools, Run workflow*.
   - Pick **list-channels**. The log should say `Facebook -> 'Solvix...'` and `Instagram -> 'solvix0'`. If it says you have two Facebook (or two Instagram) channels, add a secret `BUFFER_FACEBOOK_CHANNEL_ID` (or `BUFFER_INSTAGRAM_CHANNEL_ID`) holding the id printed next to the right one.
   - Pick **rehearsal**. The log should end with `REHEARSAL OK`, and Buffer should show two test **drafts**. Delete them in Buffer.
7. **First real day.** That evening (GitHub can be late; give it until midnight) open Buffer (*Content, Calendar*): two posts should wait for tomorrow 07:00. Next morning check the Page and Instagram, and that the **Buffer tools** run at 07:41 is green.
8. **Switch off the Make.com timer** ("Solvix daily post timer (7:00 AM)": Make.com, Scenarios, switch it OFF) once the first morning worked. Leaving it on for that first morning is safe: it finds the post already made and stops. Keep the Make.com posting scenario for a week as your way back.

## If you see a red X
Open the run and read the message; it is written in plain words. The usual ones:
- *"did not accept the API key"*: the key ran out or was replaced. Make a new key (step 4) and replace the secret.
- *"no Instagram channel"* or *"no Facebook channel"*: reconnect it in Buffer (step 2 or 3).
- *"Already created in Buffer: Facebook ..."*: Facebook is fine, Instagram failed. Add the Instagram post by hand in Buffer. Do not tick "Post again" for that day, or Facebook gets it twice.
- *"could not fetch the picture"*: the picture must be public. The web-scraper project has to stay public.
- *"Today's Buffer post needs a look"* (the 07:41 check): open Buffer and see whether it went out; if not, post it by hand. If the message says Buffer "did not understand", tell the Builders.

**Go back to Make.com in one minute:** delete the `BUFFER_API_KEY` secret and switch the Make.com timer back on. A post already waiting in Buffer still goes out; delete it in Buffer if you don't want it.

## What we could not check (28 Oct 2026)
- The team could not reach Buffer's developer pages or `api.buffer.com` from the cloud session, so the code is built from Buffer's public docs and is **not yet tested against the real Buffer**. The rehearsal in step 6 is the first real test. Buffer's API is still "beta" and changed in May 2026; its old API closes on 1 Feb 2027 (we use the new one).
- Free plan limit: 10 waiting posts per channel. We use 1 or 2.

## TikTok (added 3 Nov 2026)
If the Buffer account also has a TikTok channel, the daily post and the Monday advert go there too. No TikTok channel = it is simply skipped. A TikTok refusal never stops Facebook and Instagram. Two TikTok channels: set the secret `BUFFER_TIKTOK_CHANNEL_ID`. Not yet tested against the real Buffer (needs the API key).

## Pet Shelf orders (added 4 Nov 2026)
One order makes a Pet Shelf post and hands it to the **Pet Shelf** Buffer (Facebook, Instagram, TikTok). It uses only `PET_SHELF_BUFFER_API_KEY`, and stops if it ever sees a Solvix channel.

**Send an order.** Phone: *Actions, Pet Shelf order, Run workflow*. Terminal:
`gh workflow run pet-shelf-order.yml -R vincent001100/web-scraper -f brief="Your idea" -f type=picture`
Add `-f mode=draft` to save Buffer drafts only. Add `-f when="2026-11-06 19:30"` (Lagos time) or `-f when=now`; blank means the next 19:30 Lagos. Add `-f reference="https://..."` for inspiration: only its title and short description are read, for the topic, and its words are never used.

**Everything is public.** This project is public, so the order text and the files on the `pet-shelf-media` branch can be read by anyone. Do not delete that branch: Buffer can fetch the media again when it publishes.

**Pictures.** Cloudflare Workers AI, model `@cf/black-forest-labs/flux-1-schnell`, free up to 10,000 Neurons a day (a hard stop on the Workers Free plan). That is about 40 pictures a day by a community formula (about 250 Neurons for 1024 x 1024 at 6 steps; not an official figure). Source: Cloudflare's [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) as shown in search results on 4 Nov 2026, because the page could not be opened directly. If Cloudflare fails, the order uses our free picture card and shows a yellow warning.

**If you see a red X,** read the message at the top of the run. It names the channel that refused and which posts were already made. *Re-run failed jobs* only retries the missing channels.

**AI label.** Instagram and TikTok videos get Buffer's AI switch. Buffer refuses that switch on TikTok photo posts, so those rely on the "Picture made with AI" line in the caption. Facebook has no such switch through Buffer.
