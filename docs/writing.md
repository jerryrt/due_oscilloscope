# Writing documents here

`docs/` carries what is **settled and will be needed again**. `CLAUDE.md`
has the split between git and issues; the row it does not spell out is
this one, and these are the rules for filling it.

## The rules

| rule | why |
|---|---|
| **General to detailed, top to bottom** | The first section is read most, so it should be the shortest. A reader who stops after one screen should still have the answer |
| **Detail lives in the code. Point at it** | A copied signature, file list or constant table drifts silently and nothing fails when it does. The tree cannot drift from itself |
| **State what is true, never how it changed** | "This section used to say five minutes" is the document keeping books on itself. That belongs in `git log`, which is durable and is where people look |
| **No issue numbers** | Issues carry what is being argued; `docs/` carries what is settled. A document that says "see #48" tells the reader the answer lives somewhere it does not. **Unless the document's subject is live work** - `HANDOFF.md` names open issues, because there the reader does have to go and join them |
| **Prefer a table** | A cell will not hold a sentence that is acquiring qualifications. The format does the editing |
| **Plain, short, accurate** | Check a claim against the tree before writing it. "Both tracks" was true once and there are three |

## Evidence is not bookkeeping

The distinction is easy to lose, and the rules above kill a document
that loses it in the wrong direction.

| keep - this is evidence for a rule | cut - this is bookkeeping about the document |
|---|---|
| "A guard that could not fail went green six times" | "This section used to claim five minutes" |
| A figure with its bench, commit and instrument | "Re-measured, because the table had drifted" |
| "The counters have lied", and the two cases | "584 collected became 587" |

A number that dates a **finding** is provenance and stays. A number that
dates the **document** is bookkeeping and goes.

## Code comments

The rules above are written for `docs/`; they hold for a comment in code
too, and the same failure shows up there in the same shape.

A comment exists to help someone read the code. The history of a bug
fix or a decision change is not that - it belongs in `git log`, which is
durable and is where people look. Where a piece of history is genuinely
load-bearing - it explains why the obvious implementation is wrong, and
a reader who does not know it will break the code - it stays. Those are
exceptions and must not become the norm.

| keep | cut |
|---|---|
| `drivers/play.c`'s "Three, not two": the ENDTX guard needs `play_produced >= play_consumed + 3`, and a reader who does not know why will "fix" it to 2 and silently corrupt the analog output | `drivers/adc.c`'s comment that quotes its own earlier, wrong arithmetic back at the reader |
| a name that points at the thing that would break | an issue number standing in for the explanation - hundreds of these sit across the tree, and the issue is not where the reader is |

`tests/test_comment_style.py` catches the first cut column - a comment
or docstring narrating what it used to say. It cannot catch the second;
that one is read, not grepped.

## Shape

| prefer | over | because |
|---|---|---|
| a table | a bulleted list | two columns are usually already there: the claim, and what it cost to learn |
| a step column | a numbered list | order survives and the reason gets its own column |
| the command | the number it prints | a number written down is a number that rots |
| a name | a citation | `stream_port.h` outlives "see the framer issue" |

## The failure this prevents

A document written as a plan, then amended in place, becomes a
stratigraphy: finished work in future tense, findings wherever they
landed, and corrections layered over corrections. It reads as history
rather than as instruction, and the reader cannot tell which layer is
current.

The tell is a document that describes itself. When a paragraph explains
why an earlier paragraph was wrong, the rewrite is overdue.
