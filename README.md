# YouTube Comment MAS

**[CS473] Team 527**

**One video. More perspectives.**

YouTube Comment MAS is a comment-grounded multi-agent system for exploring different viewpoints in a YouTube discussion. Its web interface, **Re.View**, helps you write down your starting opinion, explore perspectives found in public comments, talk with agents representing those perspectives, and reflect on what stayed the same or changed.

Instead of giving you only a single summary, the system keeps disagreements, conditions, and alternatives visible. Each agent has its own source comments, and its replies link back to the comments it used.

**[Try the live application](https://commentmas.vercel.app)** · [Run locally](#run-locally) · [How the agents work](#how-the-agents-work) 

![The Re.View start screen, with a new-video form and a completed example](docs/images/start.png)

## Start with the completed example

If this is your first visit, choose **Explore example** on the [start screen](https://commentmas.vercel.app). You can move freely between **Initial view → Explore → Converse → Reflect** to see the entire experience without waiting for a new analysis.

The example follows a discussion about four-day and 4.5-day workweeks in Korea. It includes:

- A fictional starting opinion and a more conditional current opinion.
- Five perspectives derived from a real public YouTube comment section.
- Three one-to-one conversations and two group discussions: **54 messages in total**.
- Questions addressed to everyone and follow-up questions addressed to selected agents.
- Original comment evidence behind agent replies.
- A completed reflection with links to specific conversation moments.

The example opinions and user questions were written for this demonstration. Agent replies and reflection observations were generated using the public comment analysis and validated against the saved sources. The example contains no visitor's private conversation history.

The completed example is read-only. Browsing its prepared comparisons, conversations, evidence, and reflection makes **no new model requests**. Choose **Write your own view** to start a separate personal workspace.

## How to Use

### 1. Choose a video

Paste a public YouTube video link into the start screen. The system collects comments, filters them for meaningful viewpoints, discovers perspective groups, and prepares an agent for each supported group.

Under **Analysis options**, you can choose:

| Option | Behavior |
| --- | --- |
| Total comment limit | 200, 500, 1,000, or 2,000 comments; the default is 500. |
| Include replies | Replies count toward the same total limit. |
| Collect a fresh snapshot | Collect comments again instead of reusing a matching prepared analysis. |

The interface shows progress as the analysis moves through collection, filtering, grouping, and presentation. A matching analysis for the same video, options, and model can be reused within your workspace.

New analyses can take several minutes. The duration depends on the number of comments, model latency, retries, and available caches. Opening the completed example does not require a new analysis.

### 2. Write your initial view

Before talking with the agents, write what you currently think about the topic. This becomes a reference point for perspective comparisons and later reflection. Updating your view affects new conversations; existing conversations retain the initial view they started with.

### 3. Explore the perspectives

Browse cards describing each group's position, reasoning, representative comments, and share of the analyzed comments and likes. Open a card to see:

- The group's stance and supporting arguments.
- Differences within the group and limits of its evidence.
- Source comments, including the original Korean text in the prepared example.
- Similarities, differences, and an additional consideration relative to your initial view.

Comments that do not confidently belong to a group remain available under **Other opinions**. They are not forced into an agent just to complete the overview.

### 4. Converse with one or several agents

Start a one-to-one conversation, or select two to five perspectives for a group conversation. Ask an opening question, let the agents respond, and use follow-up questions to explore trade-offs.

In a group conversation, you can:

- Address everyone or select particular agents.
- See the selected agents' **names and icons above your sent question**.
- Pause or resume agent-to-agent discussion.
- Inspect evidence for individual replies and save useful comments.
- Reopen saved conversations and retry failed replies.

Recipient selections are stored with the question, so the label survives a reload. A retry keeps the original recipients and preserves successful replies.

Automatic discussion is bounded: one resume action allows at most six additional agent turns. Pausing lets an answer already in progress finish, then prevents the next turn from starting.

![A prepared group conversation showing a question addressed to two selected agents](docs/images/conversation.png)

### 5. Reflect on your view

Write your current view after the conversations. The reflection compares it with your starting view and offers tentative observations in four categories:

| Category | What it helps you notice |
| --- | --- |
| **Stayed** | A belief or priority you kept. |
| **Changed** | A belief you revised or made more conditional. |
| **New considerations** | Something you are now weighing that was absent from your initial view. |
| **Open questions** | Something that remains unresolved. |

Where a relevant moment is available, **View this moment** takes you back to the related agent message. You can review the interpretation, edit it, provide feedback, and save your reflection.

Reflection is an aid to examining your own thinking. It does not score whether you became more correct or whether an agent successfully persuaded you.

![A completed reflection with before-and-after excerpts and links back to the discussion](docs/images/reflection.png)

## How the agents work

### The analysis pipeline

```text
Public YouTube video link
        ↓
Collect comments and replies
        ↓
Filter for meaningful viewpoints
        ↓
Discover perspectives and assign comments
        ↓
Build up to five agents with separate evidence pools
        ↓
Prepare perspective cards and English display data
        ↓
Explore → Converse → Reflect
```

**Collection.** The collector uses the official YouTube Data API v3. It retrieves newest top-level comments first and, when enabled, follows their replies within the total limit. This is a snapshot of accessible public comments, not a random sample of all viewers.

**Filtering.** Comments are retained when they express a relevant position, proposal, concern, experience, reason, or meaningful question. Clear spam, empty reactions, and unrelated content can be excluded. Ambiguous or low-confidence cases are kept separately for review. Proposed model exclusions receive a second review. Shortness, sarcasm, profanity, low likes, or being a minority opinion are not by themselves reasons to exclude a comment.

**Grouping.** The model discovers groups based on a position **and its reasons**, rather than topic words or positive/negative sentiment alone. It aims for four or five useful groups when supported, with a hard limit of five. A smaller or more homogeneous discussion may produce fewer agents. The system does not invent missing perspectives to fill a quota.

Each retained comment has at most one primary group, with optional secondary perspectives recorded separately. Uncertain or weakly fitting comments remain **Other opinions**. There is no rule that automatically discards a viewpoint because it accounts for less than 5% of the comments.

**Agent construction.** Each supported group becomes an agent with its stance, arguments, internal differences, limitations, and full set of owned source comments. Assembling this bundle is a local operation. Display copy, translations, and topic-specific symbolic emojis are prepared separately with the model.

### Evidence and conversation memory

For a new question, an agent searches only its own comments using local word and character-bigram retrieval, with Korean-aware tokenization. The model receives a limited set of relevant comments, supplemented by representative evidence when appropriate. Search queries can be translated into the detected source languages without changing the user's original question.

Replies distinguish between:

- **Comment-grounded statements**, which must reference retrieved comments belonging to that agent.
- **Reasoning**, which is identified as interpretation rather than a source quotation.
- **Uncertainty**, where the available comments cannot answer the question.

The server validates source IDs and attaches the original stored comments. Agents may read each other's messages as conversational context, but they cannot cite another group's private evidence pool as their own.

Conversation state includes the initial view, participants, messages, recipients, evidence, and pause state. The full transcript is stored, while model requests use recent messages and a small number of relevant earlier messages. Agents represent comment-group perspectives; they do not impersonate particular commenters or invent a human biography.

## Run locally

### Prerequisites

- **Python 3.10 or newer**; Python 3.13 is used by the deployment container.
- **Node.js 22.12 or newer** and npm.
- A model API key for live interactions: OpenAI, or the supported OpenRouter alternative.
- A YouTube Data API v3 key to analyze new videos.

The local Python application and analysis pipeline use the standard library. `requirements.txt` adds the Firebase Admin SDK for the cloud storage and identity backend. Firebase configuration is not needed for local mode.

### 1. Clone and prepare the environment

```bash
git clone https://github.com/angelaoh0619/Youtube-Comment-MAS.git
cd Youtube-Comment-MAS

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
```

On Windows, activate the virtual environment with `.venv\Scripts\activate`.

Edit `.env` and replace the placeholders with your own values:

```dotenv
YOUTUBE_API_KEY=your_youtube_data_api_key
OPENAI_API_KEY=your_openai_api_key
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-6.2-sol
OPENAI_REASONING_EFFORT=medium
```

The model above is the repository's configured default. Set `OPENAI_MODEL` to a model available to your account that supports the structured output used by this application. Reasoning effort is configurable as `low`, `medium`, or `high` for supported reasoning models.

For OpenRouter instead, select it explicitly and use a model that supports structured outputs:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=openai/gpt-4.1-mini
```

An explicit provider selection does not silently fall back to another provider. Environment variables take precedence over `.env`.

Keep real credentials in `.env`, which is ignored by Git. Model and YouTube keys belong on the Python server, never in `VITE_*` variables or frontend source code.

### 2. Install the bundled example

```bash
python scripts/setup_example.py
```

This copies the curated public analysis into the default runtime location:

```text
data/processed/BAHKmi4F1L8_20261026-144540/
```

Setup validates the prepared conversations and evidence without calling a model. Re-running it is safe when the bundled files match. If different analysis files already exist, it stops rather than overwriting your work. Use `--data PATH` to install into another folder, and pass the same path to `web_server.py --data PATH`.

The server initializes a model client at startup, so configure a model key even if you initially plan only to browse the example. Browsing the completed example itself uses prepared content. A YouTube key is needed when you submit a new video, not to open the existing example.

### 3. Build the frontend and start the server

```bash
cd frontend
npm ci
npm run build
cd ..

python web_server.py --local
```

Open **http://127.0.0.1:8000**. The Python server serves both the built frontend and `/api` routes.

`--local` explicitly uses local storage and ignores Firebase backend settings. The frontend also bypasses Firebase sign-in on localhost. Local mode is a development workspace on your machine.

To use a different port:

```bash
python web_server.py --local --port 8011
```

Rebuild the frontend after changing its source when using the Python server's built-in static serving.

### Frontend development

Keep the Python server running on port 8000. In a second terminal:

```bash
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173**. Vite reloads UI changes and proxies `/api` to the Python server on port 8000.

## Project structure

```text
.
├── README.md
├── collect_comments.py          # YouTube URL parsing and official API collection
├── filter_comments.py           # Meaningful-opinion filtering and review
├── group_comments.py            # Perspective discovery, assignment, and summaries
├── perspective_agents.py        # Agent bundles, retrieval, replies, and sessions
├── analysis_pipeline.py         # Video library and resumable local analysis jobs
├── cloud_analyses.py            # Durable analysis artifacts and cloud job leases
├── web_data.py                  # Display data, translations, and view comparisons
├── web_server.py                # HTTP API, conversations, discussion, and reflection
├── recorded_example.py          # Immutable walkthrough and source validation
├── firebase_backend.py          # Verified identities and user-scoped Firestore stores
├── llm_client.py                # OpenAI and OpenRouter structured-output clients
├── frontend/
│   ├── src/                     # React + TypeScript application
│   ├── public/assets/           # Local SVG assets
│   └── tests/                   # Playwright browser tests
├── examples/
│   ├── four-day-week.json       # Authored walkthrough snapshot
│   └── sample-analysis/         # Portable public analysis and matching walkthrough
├── scripts/
│   ├── setup_example.py         # Install the bundled sample without paid API calls
│   ├── prepare_example_journey.py
│   ├── prepare_deploy.py
│   ├── deploy_backend.py
│   └── deploy_frontend.py
├── tests/                       # Python unit and API tests
├── docs/images/                 # Screenshots of the fictional completed example
├── Dockerfile
└── requirements.txt
```

### Runtime files

New video analyses are stored under `data/analyses/<analysis_id>/`. Each analysis separates its source and results by stage:

| Folder | Contents |
| --- | --- |
| `00_source/` | Collected comments and detected source-language context. |
| `01_filter/` | Retained, excluded, and review comments; filter decisions and caches. |
| `02_group/` | Groups, assignments, summaries, and other opinions. |
| `03_agents/` | Agent bundle and individual profiles. |
| `04_web/` | Display catalog, translations, comparisons, conversations, and reflections. |

The CLI chat tool stores its sessions under `03_agents/sessions/`. Browser preferences and some local-mode user state use browser storage; deployed user records are saved through the authenticated backend.

The repository excludes runtime data, personal conversations, local environment files, build outputs, deployment credentials, and debug logs. `examples/sample-analysis/` contains only a curated public snapshot and the explicitly fictional completed walkthrough. Its metadata paths are portable; raw collection files and model batch caches are not included.
