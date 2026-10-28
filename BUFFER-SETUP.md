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
