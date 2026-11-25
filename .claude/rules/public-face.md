---
paths:
  - "README.md"
  - "REFERENCE.md"
  - "CHANGELOG.md"
  - "CONTRIBUTING.md"
  - "docs/**"
  - "demos/*/README.md"
  - "demos/*/TRANSCRIPT.md"
---

> **This is the public-face profile of this repository.** It loads when one of the public
> documents below is opened, and it says who each layer of the documentation is written for, in
> what character and within which limits, so that an edit is made for its reader and not for its
> author. It is reference, not a task list: nothing here is an instruction to act on right now.

## The layers of the public face

One row per layer. A file belongs to exactly one layer; two audiences in one file is the
God-README pattern this profile exists to catch.

| layer | files or globs | audience | character | language |
|---|---|---|---|---|
| front door | `README.md` | a stranger with an MCP client who develops for, or investigates, a program running in MAME (an arcade board, a home computer); the first thing they read | captivate, then practical, and short: one sentence on what they can do now, a demo moving, the install for their client, a first question to ask, what else they can ask, and links. The terminal kept apart from the explanation: what is typed and what came back in code blocks, prose outside them. No history and no measurement: the WHY of a contract is the reference's | English |
| reference | `REFERENCE.md`, `docs/reference/*.md` | somebody already using the server who comes back for one tool: what to ask, what it takes, what it returns, what it refuses, and why | each tool's entry in the one order below, example first; complete, precise, scannable, and read one tool at a time, on a phone too. `REFERENCE.md` holds the index, the envelope every reply carries and the contracts that cut across tools; each family of the roster has its own page. Pages in the roster's order; a family both servers have keeps one name on both. The WHY told as a reason, never as a record: no figure, no date, no "used to" | English |
| contributor guide | `CONTRIBUTING.md` | somebody changing the server: how to run its battery and its live tiers, what proves a change, what the tests hold | practical and short: the commands, what each proves, what a red means. No contract restated: the reference holds it | English |
| demo guide | `demos/*/README.md` | somebody who wants to watch one investigation run end to end on a program they can get legally, and try a step of it | practical: the demo moving, what it shows, how to get the program, the one command, steps to try, the tools it uses, what the run prints | English |
| changelog | `CHANGELOG.md` | somebody upgrading the server | what a client notices, one entry per change, newest first | English |
| store guide | `.scry/README.md` | somebody reading this repository's own `.scry/` store | practical: what each file of the store is and what reads it | English |
| demo transcript | `demos/*/TRANSCRIPT.md` | somebody checking what a demo guide claims against every call and reply of the run | reference: generated, complete, never edited | English |

## What is public and what is not

- Public: the documents the layers name, and the captures and motion they show.
- Not public and not this profile's business: the fixture READMEs under `tests/fixtures/`,
  read only by whoever touches those doubles.
- Extra READMEs kept public: `.scry/README.md`, the store guide.

## Countable limits

They serve the reader, so a fact is never what gets cut to meet one: it moves to the layer that
reader goes to for it. Words are counted in prose, outside code blocks and generated blocks.

| layer | limit |
|---|---|
| every layer | a paragraph is at most 3 sentences and 60 words (4 and 80 in the reference's why); a sentence at most 30 words |
| every layer | a table has at most 3 columns and 12 rows; wider data is a list |
| every layer | a code block showing has at most 12 lines of at most 100 columns; longer output sits in a closed `<details>` |
| front door | the opening is one bold sentence of at most 25 words |
| front door | at most 150 words between the title and the install block, the title's words in and the generated lead block out (`tests/test_reference_pages.py` holds it, and refuses a second lead marker) |
| front door | "What you can ask" has at most 6 bullets, each a question of at most 12 words in quotes, the tools that answer it, and one sentence of at most 20 words |
| front door | at most 2 generated flows, each at most 5 calls, each reply at most 12 lines |
| front door | under 16 KB, the generated blocks included |
| reference | a tool's one sentence is at most 25 words, and so is the line that says what a family holds |
| reference | a tool shows at most 3 paragraphs of why; more sits in a closed `<details>` |
| reference | where an example can be tried is at most 2 sentences and 40 words; an argument's, a returned field's and a refusal's line at most 2 sentences and 30 words each |
| demo guide | at most 120 words above "Run it"; its first paragraph at most 60 |
| demo guide | each moment one sentence of at most 25 words |
| demo guide | 2 to 4 steps under "Try it yourself"; the whole prompt as numbered steps of at most 30 words each, in a closed `<details>` |

## The front door: its sections and their order

1. One centred `<h1>` holding the logo and the repository's name.
2. A centred `<p><b>...</b></p>`: what the reader can do now; under it a row of four links,
   Install, What you can ask, Demos, Reference.
3. The lead block, generated (*Generated documents*): the lead demo's clip linked to its
   guide, a caption, and one step as a table of three rows, You ask / Your client calls /
   SCRY answers. A lead declared with `learns=True` has a fourth row, "Your client learns",
   holding the step check's own summary. The call row cuts every string longer than 9
   characters to its first and last 4 (`scry_core.demo.LEAD_STRING_ENDS`, `demo.narrow`),
   so a 390 px phone holds the table; the whole call is in the demo's `TRANSCRIPT.md`.
4. `## Install` (*Install*), with two `###` subheadings, "Add it to your client" and
   "Your first question".
5. `## What you can ask`.
6. `## See it run`: a grid of the other demos' stills (never the lead's), each
   `demos/<name>/screen.png`, the screen that demo's run ended on, linked to its guide, every
   one at the same height (`width` and `height` set from the still's own shape), in centred
   rows of at most four. No clip moves there: each guide shows its own. Then each demo in one
   sentence, linked; the generated flows.
7. `## Set up SCRY in your own project`.
8. `## Platforms`.
9. `## The tools`: a pointer to the index `REFERENCE.md` generates, never a table typed by hand.
10. `## Going further`, `## Licence`, `## Credits`.

This server's front door and `REFERENCE.md` carry the same second-level headings in the same
order as scry-dosbox-x's. A section about something only one emulator has is allowed, by name:
DOSBox-X's hardware, guest files and debugger channel; MAME's console. Any other section one has
and the other lacks is a finding.

## Install

- One sentence of what the reader needs, then the clone, in one `sh` block.
- "Add it to your client": one `<details>` per client, in this order, Claude Code's `open`:
  Claude Code, Codex, Claude Desktop, Cursor, VS Code, Copilot CLI, Gemini CLI, Antigravity,
  Devin, Another client. Each holds at most 2 sentences and one block.
- Every block starts the same server the same way, `uv run --directory <the clone> scry-mame`
  over stdio, under the name `mame`, spelled as that client's own documentation spells a
  local server. The pages each block is built from:

  | client | the vendor's page |
  |---|---|
  | Claude Code | https://code.claude.com/docs/en/mcp |
  | Codex | https://learn.chatgpt.com/docs/extend/mcp?surface=cli |
  | Claude Desktop | https://modelcontextprotocol.io/docs/develop/connect-local-servers |
  | Cursor | https://cursor.com/docs/context/mcp |
  | VS Code | https://code.visualstudio.com/docs/agents/reference/mcp-configuration |
  | Copilot CLI | https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers |
  | Gemini CLI | https://geminicli.com/docs/tools/mcp-server/ |
  | Antigravity | https://antigravity.google/docs/mcp |
  | Devin | https://docs.devin.ai/cli/extensibility/mcp/configuration.md |

- A block says only what that page says or what was run here: no advice about a client nobody
  ran, no claim about a product's name or history. A block that names a file names the path the
  vendor names.
- "Your first question" closes the section: one prompt of at most 25 words in a quote, needing
  nothing but a ROM mamedev.org distributes for free, and one sentence on what the client answers.
- The blocks are generated from one table in scry-core, between `<!-- scry-install:begin -->`
  and `<!-- scry-install:end -->`, so this front door, scry-dosbox-x's and the site cannot disagree.

## A tool's entry: its fields and their order

On its family's page, per tool, each part under its own third-level heading so a page of the
site can list them:

1. `## \`name\``, then what it does for a person: one sentence (`docs/reference/asks.json`,
   `what`), and the signature in a `text` block.
2. `### Try it`: where it can be tried (`on`), then the example in the shape below.
3. `### The <count> <values>` ("The five modes", "The three methods"), for a tool whose first
   choice is an argument with named values: a table of at most 3 columns, one row a value.
4. `### Arguments`: a list in the signature's order, each `name` (type, `required` or its
   default) and one sentence.
5. `### What comes back`: the fields a reader acts on, at most 6, each with one sentence; every
   field and its type in a closed `<details>`.
6. `### What it refuses`: a list, one refusal a line.
7. `### Why it works this way`: at most 3 paragraphs; more in a closed `<details>`, which may
   also hold a list, a table of at most 3 columns or a code block.
8. `### Related tools`: links to the tools a reader reaches for next.
9. The contract the client receives: the tool's own description, whole, as text in a closed
   `<details>`. It is the contract, so it is never reworded here.

Every part is generated: the registry gives the signature, the types, the fields and the
contract; `asks.json` gives each sentence, and a sentence over its limit is refused. A tool
with nothing to say under a heading has no such heading, but for two every entry keeps:
`### Arguments`, where a tool that takes none says so, and `### What comes back`. A reader
looking for either finds the answer in the same place. A reply field table of every field
showing, an example placed last, and a tool name in a tinted box are what this order replaces.

## An example: its shape

The same shape in the front door, the reference and the demo guides:

1. **Ask**: what a person would type to their client, at most 25 words, one request
   (`asks.json`, `ask`; a demo's `Step.ask`).
2. **Call**: the call as written, `tool(argument=value)`, at most 3 lines. A call too long
   for them is cut where the cut shows (`perform(steps=[… 19 items])`), and the whole call is
   in the demo's `TRANSCRIPT.md`.
3. **Reply**: an excerpt of the real reply, at most 12 lines: the fields that make the point,
   and "N of M fields" beside it.
4. How to read that reply: at most 2 sentences and 40 words, which say in plain words any name
   of ours the excerpt shows (*Vocabulary*).
5. The whole reply in a closed `<details>`, in the reference and the demo guides. The
   front door's generated flows leave it to the guides, to stay under the README's size limit.

- A reply is copied from a run, never typed: a demo's transcript, or a live run's.
- **An example can be tried.** Its call works on a demo the reader can get: `starfire` or `gridlee`, on ROMs mamedev.org distributes for free. A tool
  none of those reaches says which program its example ran on and what that program needs.
- An example has at most two calls, the second only when the first call's point is what a
  later call of the same run answers.
- A sentence that says where an example can be tried calls the run it comes from "the example
  session", and `REFERENCE.md` says once what that is and how its paths are spelled.
- A reference example is a run's own: its call and its reply are copied from the committed
  transcript of the tour (`docs/reference/tour/TRANSCRIPT.md`, one checked session on Gridlee
  that calls each tool once) or of a demo, where a step of a `perform` counts as that tool's
  call. A tool Gridlee cannot serve keeps an example from a run of the live tests, and its
  entry says what kind of program it needs.

## A demo guide: its sections and their order

1. The title: the program, and what the demo shows, in words a stranger knows.
2. The demo moving, centred (`<p align="center"><picture>...`), its moments under it
   (*Demo motion*).
3. One paragraph of at most 60 words: what it shows.
4. How to get the program: `## The ROM`, or `## The program`.
5. `## Run it`.
6. `## Try it yourself`: 2 to 4 steps, each an example in the one shape under a `### N. title`
   heading (`#### N. title` in a README's example calls), so GitHub's outline lists them; the
   whole prompt folded.
7. `## Tools this demo uses`: a table of two columns, `Group` and `Tools`. A group is a family of
   the reference, by its own name and linked to its page; no label is invented for a row.
8. `## The transcript`.

## Demo motion

A demo is shown moving, never as a still alone.

- **One file per demo**: `demos/<name>/loop.webp`, an animated WebP that loops for ever.
- **The moments and the length the motion rule allows** (`motion.CUTS_MAX` of them, `motion.LOOP_SECONDS` in all, each between `motion.CUT_SECONDS`' bounds). A moment is a stretch
  where the screen changes because of a call the demo made, declared in the demo as
  `Moment(after, until, caption, skip=0, frames=0)`: what the screen did from the end of step
  `after` to the end of step `until`. `until` is a `record` step right after `after`, whose
  file is the moment, or any later step of a session that records its own video, whose stretch
  between the two steps is cut. `frames` of it are shown from its frame `skip`. Less is more: a
  demo with one strong moment shows one.
- **Nothing is staged.** The frames are the run's; a moment is cut, never slowed, held or
  composed, and nothing is drawn over it: what the call did is the transcript, the chat and the
  page's words.
- **Frames**: the machine's own (a capture the emulator doubled is halved back), at most 30 a
  second. Rows and columns at the clip's edges that are one colour, the same in every frame,
  are cut (`scry_core.motion.kept`), and `screen.png` is cut by the same box at its own scale
  (`motion.still`); `stale` takes a still that is a rectangle of the run's capture as that
  capture. A README cannot style an image, so the frames are then written scaled up a whole
  number of times, each pixel a sharp block, as far as 960 x 720 holds them
  (`scry_core.motion.FIT`).
- **Weight**: at most 400 KB a file. Lossless where it fits, else lossy; a file past the budget
  is refused, and the demo shows less.
- **Made by** `demos/<name>/demo.py --update-readme`, in the run that writes the README block and
  `screen.png`: ffmpeg decodes the recording and libwebp's `img2webp` assembles it. Without
  either program the update is refused by name. The file is committed; it is not byte-stable, so
  a check asks that it is there, never that its bytes are the run's.
- **Shown** in the demo guide above its first paragraph, in the front door once, and on the site
  wherever the demo appears, always as
  `<picture><source media="(prefers-reduced-motion: reduce)" srcset="screen.png"><img src="loop.webp" alt="..."></picture>`,
  so a reader who asks for no motion gets the still. `alt` says what moves.
- **Each moment has its sentence** under the picture, naming the call that made it. The site
  lights each sentence while its moment plays, timed by the durations of the file's frames, so a
  sentence says what is on screen during its own moment and nothing else.

## Generated documents

| document | generated from | regenerated by |
|---|---|---|
| `REFERENCE.md` and `docs/reference/*.md`, the blocks between their `<!-- scry-reference:begin NAME -->` and `end` markers; `docs/reference/examples.json` | the server's own tool registry (names, descriptions, argument schemas, reply models, roster); the examples from the committed demo transcripts and, for a tool no demo calls, a live run's; each tool's sentences (`what`, `ask`, `on`, `call`, `shows`, `reads`, `arguments`, `returns`, `refuses`, `why`, `related`) and each family's one line from the hand-written `docs/reference/asks.json` | `python -m scry_core.reference scry_mame.server:REFERENCE --write` (the examples with `--examples docs/reference/tour/TRANSCRIPT.md demos/*/TRANSCRIPT.md`, after `docs/reference/tour/tour.py` has run), held by this repository's drift test |
| `README.md`'s block between `<!-- scry-install:begin -->` and `<!-- scry-install:end -->` | scry-core's table of clients | `python -m scry_core.install scry_mame --write`, held by the same drift test |
| `README.md`'s block between `<!-- demo-lead:begin NAME -->` and `<!-- demo-lead:end NAME -->` | the lead demo's run (`Demo.lead`): its clip linked to its guide, a caption, one step as a table | `demos/lineup/demo.py --update-readme` |
| `README.md`'s blocks between `<!-- demo-flow:begin NAME -->` and `<!-- demo-flow:end NAME -->` | the steps the demo marks `shown`, from a run of that demo (starfire and gridlee) | `demos/<name>/demo.py --update-readme` |
| `demos/*/README.md`'s block between `<!-- demo-motion:begin -->` and `<!-- demo-motion:end -->` | the demo's `loop.webp`, `alt` and the caption of each `Moment`, timed by the frames the run cut | `demos/<name>/demo.py --update-readme` |
| `demos/*/README.md`'s block between `<!-- demo-transcript:begin -->` and `end`, `demos/*/TRANSCRIPT.md`, `demos/*/screen.png` and `demos/*/loop.webp` | a run of the demo against the real emulator; the steps to try and their sentences are the demo's own, on the steps it marks | `demos/<name>/demo.py --update-readme` |

The prose outside the markers is hand-written. A generated block is never edited by hand: a
finding about it is a finding about the tool's code.

## Captures

- This repository generates its own: the captures and the motion a document shows are produced
  by the server itself from a script tracked here, never captured by hand.
- Policy: the front door shows one demo moving and at least one flow end to end; each demo guide
  shows its program moving.
- Stale: a capture is stale when the tool or the program it shows changed after it; the script
  is rerun, and a second run reproduces what is committed (the motion excepted, as above).

## A thing is called what it is, and a page never shows our bookkeeping

- **A title, a heading and a link's text name the thing itself**, in the words somebody who
  has never seen SCRY would use for it: "Knowledge base", never a phrase coined for its effect
  ("Names for numbers"). If the reader has to work out what the title refers to, the title is
  wrong.
- **A public page says what a reader gets, never how we are building it.** No count of what
  is written and not yet served, no state of our own pipeline ("held back", "pending",
  "confirmed by a second reader", "not complete yet"), no account of how an entry comes to be
  shown. What the thing has and what it answers is the whole of it; a product's page does not
  list its own backlog.
- **Where a reply shown as an example carries such fields, the page shows the reply without
  them.** They stay documented only where a tool's reply is described field by field, each in
  the words that field needs and no more.
- A sentence that describes our process and not what the visitor gets is a finding, and so is
  an option offered for a page that would expose it.

## Vocabulary: words a programmer who never saw SCRY knows

- Headings and running text use words a programmer who has never seen SCRY knows. A heading says
  what is under it in those words: "Tools this demo uses", never "What it walks".
- A term of ours appears only if it is the name of a tool, an argument, a reply field, one of
  its values, or a family of tools. It is set in code type (a family's name as a plain capital
  word), and where it first appears on a page it is explained in plain words, in that sentence
  or the next. A page is one document, or one page of the site.
- A wording a server prints inside a reply is shown as printed, because a reply is copied and
  never typed; the sentence that reads the reply says it in plain words.
- A metaphor is not a term. A thing is called what it is each time, even when a shorter image
  has become a habit here.
- An emulator's own vocabulary (MAME's, DOSBox-X's, DOS's) is used as its documentation uses it,
  and a word of it a programmer may not know is explained once the same way.
- The table is part of the rule. A word of its left column, used in that private sense in a
  heading or in running text, is a finding, and the right column is what to write. A coinage
  the table does not hold yet is a finding too: it is added with its plain words.
- This file's own labels for the layers ("front door", "demo guide") are names inside this
  file. A public document says "the README" and "the demo's page".

| ours | write |
|---|---|
| Names for numbers | Knowledge base |
| What it walks | Tools this demo uses |
| A first answer | Your first question |
| From an investigation to a bench | From a session to a test that replays itself |
| The battery | The checks |
| The live tier | Tests against a real emulator |
| The store | The `.scry/` folder / What is saved between sessions |
| The route | How input gets into the program |
| The code pane is the control | Checked against the debugger's own disassembly |
| The one table | Tools that answer while the program runs |
| Recipes | Start profiles |
| Sessions (in `.scry/`) | Saved step lists |
| Two machines | Two emulators |
| Shared core | scry-core, the shared package |
| walk | sequence of steps / destination rectangle / list of files |
| front door | the README |
| flow | the README's example calls |
| bench | replay test / folder of test programs / live-test helper |
| tier | tests against a real emulator / opt-in tests |
| battery | the checks |
| desk | your screen and keyboard |
| kata | checked demo |
| roster | tool list |
| envelope | the fields every reply carries |
| survey | the readings taken at each stop |
| store | the `.scry/` folder / the saved breakpoints file |
| recipe | start profile |
| park | stopped at the debugger |
| place | address / resolved to an address |
| census | write log |
| LATCHES | stays set until `close` |
| law | rule |
| rung, ladder | the first of these that is set |
| broom | way of clearing |
| golden, blessed | reference capture / reference build |
| held to | matches / is compared with |
| judged | checked |
| signed | fingerprinted |
| rest | confirmed stopped |
| fly | fast-forward |
| release | resume |
| alarms | warnings |
| ride | is included in |
| matrix, cell | the live test script / test case |
| probe | description test / version check |
| residual | known failure, tolerated |
| sweep | cleanup pass / manual check |
| gate | check |
| drift | out of date |
| surface | the tools and their replies |
| instrument | check |
| seam | test override |
| guardian | watchdog |
| highlight, epilogue | featured step / closing steps |
| the loop | the demo's clip |
| one-off images | say the thing itself |
| the owner, the reader | you |
| answer by name | by your program's symbol names |
| proves they landed | checks the program took them |
| the beam | the screen line being drawn |
| heavy debugger | a DOSBox-X built with heavy debugging |
| arrival | reaching the target |
| channel | log / debugger connection |
| stub | the input helper inside DOS |
| guest | the program (inside the emulator) |
| double | stand-in for tests |
| dumper | table writer |
| cold, hot | rarely run / often run |
| harness, binding | boot script / per-emulator settings |
| known answer | reference data |
| lap | repetition |
| batch | the loaded symbol table |
| scratch | temporary folder |
| cap | the client's text limit |
| ledger, canary | run log / preflight check |
| call boundary | call wrapper |
| fold | merged tool |
| bound | time limit |
| live run | a run against the real emulator |
| declare (a repository) | keeps in `.scry/` |
| Advance (a family) | Run |
| Declarations (a family) | Breakpoints |
| Lists (a family) | Sequences |
| Store (a family) | Project |
| Film (a family) | Timeline |
| N survivors (a scan's summary) | N left |
| posted, unverified | sent, reaction not checked |
| effect seen, effect not seen | reaction seen, no reaction seen |
| N retraces (a summary) | N frames |
| kept N (promote to review) | N saved for `promote` |

Kept and explained where they first appear, never renamed by a document:

- The families, by the names the servers send: Run (the tools that let the program run and stop it again), Breakpoints (breakpoints and watches, saved by name and set again by the server), Sequences (the tools that run several calls as one: `perform`, `drive`), Project (the tool that saves into the repository's `.scry/` folder: `promote`), Timeline (MAME's tools that show the frames in which a write happened). "Screen map" names the `screen_map_*` tools and the file they read: a program's screens and the named areas of each, explained where it first appears.
- The names: `promote`, `kept`, `draft`, `not_settled`, `settle_seconds`, `verdict`, `OTHER_STOP`, `ELAPSED`, `TARGET`, `TIMEOUT`, `altered`, `control`, `control_silent`, `anchor`, `mark`, `since_mark`, `ref`, `held`, `recorded`, `diverged`, `route`, `armed`, `pending`, `unresolved`, `unarmable`, `stale`, `foreign`, `inherited`, `orphan`, `declaration`, `regpoint`, `shared`, `presence`, `tally`, `show`, `change`, `count`, `capture`, `freeze`, `consolidated`, `verified`, `perform`, `drive`, `e9`, `no_channel`, `enrichment`, `unaccounted`, `surveyed`, `superseded`, `cut`, `posted`, `arrived`, `pen`, `profile`, `keep_noise`, `heavy_debug`, and every other tool, argument, field and value the reference lists.
- What a transcript prints for a value that changes from run to run: "<volatile>, <host>, <run>, <time>", said once at the head of each transcript.

## Limits

- Language: every public document here is in English. This line is the declaration; there is no
  other language rule to cite.
- A public document over 64 KB whose headings also belong to more than one layer is reported as a
  God README with a proposed split; either signal alone is a size or a long file. A front door
  carrying a reference section, or a reference opening with a pitch, is the pattern.
- The front door closes with the credits line, verbatim, its links resolving; it is attribution
  the project ships, not a leak, and a front door without it is the finding:

  `Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).`
- The `claude` command, named where it is the program a reader runs (an install command, the
  probe that executes it), is the name of a program and not a mention of the assistant; no other
  use of the name is exempt. The same holds for the other clients' programs in the install block
  (`codex`, `code`, `copilot`, `gemini`, `devin`).
- Nothing else is exempt: a dated measurement, a paragraph about deleted machinery, a note on the
  project's own history, a home-directory path in any tracked file, or an assistant's name in a
  tracked file outside `CLAUDE.md` and `.claude/`, is a finding.
