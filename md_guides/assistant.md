# AI assistant

Two features use Claude through the Anthropic Python SDK, called from Django views. Both stay off until `ANTHROPIC_API_KEY` is set, and the rest of the site works without it.

- **Chat (#130):** the "Ask AI" button on every page. Logged-in users ask for food in plain language. Claude searches our data with read-only tools.
- **Picked for you (#129):** logged-in users with a saved profile get Top Picks ranked by Claude, each with a short reason. If anything fails, the page shows the normal Top Picks.

## Setup

Add these to `.env`:

```bash
ANTHROPIC_API_KEY=your-key
# Optional:
ASSISTANT_MODEL=claude-haiku-5-5
ASSISTANT_DAILY_MESSAGES=50
```

Run `import_datasets` if your database has blank cuisines, because cuisine and diet filters depend on them.

## How chat works

`assistant/chat.py` sends the message, the system prompt, and the user's saved preferences to Claude. Claude can call up to four rounds of tools from `assistant/tools.py`, and Django runs each one as a fixed ORM query:

| Tool | Purpose |
|---|---|
| `search_places` | Restaurants, farmers markets, and Shop Healthy stores, optionally near the user |
| `get_place_details` | Inspection history, cached Google data, visitor ratings |
| `get_menu_nutrition` | Calories and nutrients for large chains (MenuStat) |
| `get_my_ratings` | The logged-in user's own ratings |

The conversation is kept in the user's session as plain text, up to 20 turns. "New chat" clears it.

## Location

The chat panel has a "Use my location" button that uses the browser's location. Browsers only allow this on HTTPS or localhost, so on a plain HTTP deployment it reports that it can't get a location.

Most restaurant records have no coordinates, so a nearby search uses a live Google Places search around the user, nearest first. Farmers markets and grocery stores use their dataset coordinates. Coordinates go to Google for that search and are never sent to Anthropic. Claude is only told whether a location is shared.

Without a browser location, Claude uses a ZIP code or borough from the message, then the ZIP code and borough from the user's home address.

Each message can make at most two Google searches, and each one is a paid request. Personalized Top Picks use the home borough only.

## What the model can see

`assistant/profile.py` decides this. Claude gets favorite and disliked foods, health goals, allergies, a mood check-in from the last 24 hours, and the ZIP code and borough from the home address. It never gets the user's name, email, phone, street address, coordinates, photo, age, gender, height, or weight. The chat panel tells users what's sent to Anthropic.

## Safety rules

- **Allergies:** no filter hides cuisines. Claude sees the user's allergies, uses what it knows about each cuisine to steer away from risky places, and names the risk. It has no ingredient data, so it can be wrong. The prompt forbids calling a place safe, and the UI tells users to confirm with the restaurant.
- **Dislikes:** cuisines named in `disliked_foods` are left out of the Top Picks shortlist. Chat leaves them to Claude's judgment.
- **User data:** tools take the user and location from the request, so a prompt can't reach someone else's data.
- **Output:** replies are shown as plain text. Links are built by the server from places the tools returned.
- **Cost:** chat is limited per user per day. The count is kept per server process, so the real limit can be somewhat higher. Rankings are cached for 6 hours and refresh when the profile changes.

## Deploying

1. Add `ANTHROPIC_API_KEY` to `.env` and run `deploy/push_ssm_params.sh`.
2. Then add this line under `environmentsecrets` in `.ebextensions/secrets.config`:

   ```yaml
   ANTHROPIC_API_KEY: arn:aws:ssm:us-east-1:322134621417:parameter/nycfood/ANTHROPIC_API_KEY
   ```

Do these in order. Instance startup fails if `secrets.config` lists a parameter that doesn't exist yet.

## Tests

`assistant/tests.py` needs no key and makes no API calls. Most tests mock the client, and `RealSdkTests` runs the real SDK against a fake server to check request and response handling.
