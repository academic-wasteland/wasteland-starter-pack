# One workspace for towns and operators

Open the starter dashboard at **http://127.0.0.1:8394/** after running:

```sh
python -m wasteland --state .town dashboard
```

The multi-town cockpit uses the same workspace. Robert's installation is at
**http://localhost:8393/**. The generic cockpit default remains port 8390.

## Read first, inspect when needed

The default **Messages** view lists recorded requests, answers and conversation
activity. Select a row to read the entire message, including text beyond its
preview. Search checks full message text, participants and operations. Town and
kind filters narrow the results. **Message data** expands the structured payload;
**Identifiers & recorded links** keeps protocol IDs out of the reading path.
**Download message** exports the selected message and its linked messages as JSON.

Linked messages come from explicit parent IDs, never from nearby timestamps or
agent names. The view does not infer hidden reasoning or remote execution. A sent
or delivered message is not proof of an agent answer. The list is a recent local
window (400 exchanges plus up to 400 conversation events in the cockpit; the
starter also includes its bounded inbox, outgoing and durable worker history).
It is not a complete archive of every town in the wasteland. Historical records
that never contained prose are labelled as structured messages.

Updates preserve the selected message and expanded payload. **Pause updates**
freezes automatic refresh while agents continue working; you can still open
messages. A connection error retains the previous view and shows an error.
The cockpit's source selector also opens each locally managed town's agent mail,
including read and unread messages. The mailbox controls remain under Operations.

## Compose and discover

**Conversations** retains named people, sending towns, agent selection, resource
references, phenotype label–ID pairs, reports and the observed task trace. The
route diagram and identity details are expandable. **Towns & services** searches
the discovered directory and opens a composer addressed to a town or agent.
FAIRhaven provides the richer service/resource registry. A capability advertisement
does not grant access or prove service availability.

**Operations** contains the existing worker, resource and trust settings in the
starter; the cockpit also provides task watch, sessions, mail and authority
approval controls. Its URL is `/operations`. Existing cockpit bookmarks such as
`/#decisions` redirect to the corresponding Operations view. `/conversations`
remains a supported entry point. The diagnostic demo routes are unchanged.

## Access boundary

This is one shared interface with two server adapters, not a new public login
system. Both remain local operator interfaces with existing loopback/Host guards
and per-process write tokens. The browser receives no relay bearer credentials.
The cockpit only exposes mail for locally configured towns. Person memberships
are attribution, not authorization; every operator with access to this local
workspace retains the same administrative access as before. Public visitors
continue to use the separate demo interface, never this administrative workspace.

## Regression checks

`python tests/run_checks.py` checks the HTTP APIs, complete content, exact payloads,
acknowledged-message history, explicit links, search and access guards.

For Chromium interaction tests:

```sh
npm install --no-save --package-lock=false playwright@1.63.0
npx playwright install chromium
node tests/browser/workspace.cjs
```

The browser test starts a disposable real relay/dashboard, reads and searches a
long message, inspects a real answer and payload, observes new mail without losing
the selected message, inspects while paused, downloads, discovers a town, sends a
named local conversation, and checks the mobile layout and Operations navigation.
It does not send to live towns. CI runs it on every push and pull request.
